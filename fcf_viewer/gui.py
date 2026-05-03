import threading
import time
from dataclasses import dataclass
from typing import Iterable

import tkinter as tk
from tkinter import ttk

import nfc
from nfc.tag import Tag
from nfc.tag.tt3 import BlockCode, ServiceCode, Type3TagCommandError
from nfc.tag.tt3_sony import FelicaStandard

from .cli import SYSTEM_CODE, fix_ic_code_map, format_user_type

BASIC_INFO_FIELDS: tuple[tuple[str, str], ...] = (
    ("user_type", "利用者区分"),
    ("personal_id", "個人ID"),
    ("reissue_count", "再発行回数"),
    ("sex", "性別"),
    ("name", "氏名"),
    ("school_id_number", "学校識別番号"),
    ("issue_date", "発行日"),
    ("expire_date", "有効期限"),
    ("issue_company", "発行事業者"),
)


@dataclass
class FcfCardData:
    idm_hex: str
    pmm_hex: str
    basic_information: dict[str, str]
    fcf_un: str | None


class FcfDataExtractor:
    """Utility that mirrors the CLI logic but returns structured data."""

    def __init__(self, tag: FelicaStandard) -> None:
        self.tag = tag

    def read(self) -> FcfCardData:
        idm_hex, pmm_hex = self._polling()
        basic_info = self._read_basic_information()
        fcf_un = self._read_fcf_un()
        return FcfCardData(
            idm_hex=idm_hex,
            pmm_hex=pmm_hex,
            basic_information=basic_info,
            fcf_un=fcf_un,
        )

    def _polling(self) -> tuple[str, str]:
        try:
            polling_result = self.tag.polling(SYSTEM_CODE)
        except Type3TagCommandError as exc:
            raise RuntimeError("システム 0xFE00 にアクセスできません。") from exc

        if len(polling_result) != 2:
            raise RuntimeError("Polling 応答が不正です。")

        self.tag.idm, self.tag.pmm = polling_result
        return self.tag.idm.hex().upper(), self.tag.pmm.hex().upper()

    def _read_blocks(
        self, services: Iterable[ServiceCode], blocks: Iterable[BlockCode]
    ) -> bytes:
        return self.tag.read_without_encryption(list(services), list(blocks))

    def _read_basic_information(self) -> dict[str, str]:
        try:
            blocks_data = self._read_blocks(
                [ServiceCode(0x006A, 0x0B)], [BlockCode(i) for i in range(4)]
            )
        except Type3TagCommandError as exc:
            raise RuntimeError(
                "このカードは FCF に対応していません。(サービス 0x1A8B にアクセスできません。)"
            ) from exc

        data = blocks_data.decode("shift_jis", errors="ignore")
        return {
            "user_type": format_user_type(data[0:2]),
            "personal_id": data[2:14],
            "reissue_count": data[14:15],
            "sex": data[15:16],
            "name": data[16:32].rstrip(),
            "school_id_number": data[32:40],
            "issue_date": data[40:48],
            "expire_date": data[48:56],
            "issue_company": data[56:57],
        }

    def _read_fcf_un(self) -> str | None:
        try:
            block = self._read_blocks([ServiceCode(0x01E8, 0x0B)], [BlockCode(0)])
        except Type3TagCommandError:
            return None

        return block.decode("ascii", errors="ignore").strip() or None


class FcfViewerApp:
    """Minimal Tkinter GUI that surfaces the CLI data."""

    def __init__(self) -> None:
        fix_ic_code_map()
        self.root = tk.Tk()
        self.root.title("FCF Viewer")
        self.root.geometry("520x570")

        self.status_var = tk.StringVar(value="NFC リーダーを初期化しています…")
        self.message_var = tk.StringVar(value="")
        self.idm_var = tk.StringVar(value="-")
        self.pmm_var = tk.StringVar(value="-")
        self.fcf_un_var = tk.StringVar(value="-")
        self.basic_info_vars = {
            key: tk.StringVar(value="-") for key, _ in BASIC_INFO_FIELDS
        }

        self._build_ui()

        self.stop_event = threading.Event()
        self.nfc_thread = threading.Thread(target=self._nfc_loop, daemon=True)
        self.nfc_thread.start()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def run(self) -> None:
        self.root.mainloop()

    def _build_ui(self) -> None:
        container = ttk.Frame(self.root, padding=16)
        container.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            container,
            textvariable=self.status_var,
            font=("Helvetica", 14, "bold"),
            anchor="w",
        ).pack(fill=tk.X, pady=(0, 4))

        ttk.Label(
            container,
            textvariable=self.message_var,
            foreground="#4b5563",
            wraplength=480,
            anchor="w",
        ).pack(fill=tk.X, pady=(0, 12))

        identifiers = ttk.LabelFrame(container, text="カード識別", padding=12)
        identifiers.pack(fill=tk.X, pady=(0, 12))
        self._add_labeled_value(identifiers, "IDm", self.idm_var, row=0)
        self._add_labeled_value(identifiers, "PMm", self.pmm_var, row=1)

        basic_frame = ttk.LabelFrame(container, text="基本情報", padding=12)
        basic_frame.pack(fill=tk.X, pady=(0, 12))
        for row, (key, label) in enumerate(BASIC_INFO_FIELDS):
            self._add_labeled_value(
                basic_frame,
                label,
                self.basic_info_vars[key],
                row=row,
            )

        fcf_un_frame = ttk.LabelFrame(container, text="FCF-UN", padding=12)
        fcf_un_frame.pack(fill=tk.X, pady=(0, 12))
        self._add_labeled_value(fcf_un_frame, "FCF-UN", self.fcf_un_var, row=0)

        ttk.Label(
            container,
            text="カードをかざすと情報が自動で更新されます。",
            foreground="#6b7280",
        ).pack(fill=tk.X, pady=(8, 0))

    @staticmethod
    def _add_labeled_value(
        frame: ttk.LabelFrame,
        label: str,
        variable: tk.StringVar,
        *,
        row: int,
    ) -> None:
        ttk.Label(frame, text=label, width=14, anchor="w").grid(
            row=row, column=0, sticky="w", pady=2
        )
        ttk.Label(frame, textvariable=variable, anchor="w").grid(
            row=row, column=1, sticky="w", pady=2, padx=(8, 0)
        )

    def _nfc_loop(self) -> None:
        try:
            with nfc.ContactlessFrontend("usb") as clf:
                self._async(self._set_status, "カードをかざしてください。")
                while not self.stop_event.is_set():
                    try:
                        clf.connect(
                            rdwr={
                                "targets": ["212F", "424F"],
                                "on-connect": self._on_connect,
                                "on-release": self._on_release,
                            }
                        )
                    except IOError as exc:
                        self._async(
                            self._show_message,
                            f"読み取りエラー: {exc}",
                        )
                        time.sleep(1.0)
        except IOError as exc:
            self._async(
                self._show_message,
                f"NFC リーダーを初期化できません: {exc}",
            )
            self._async(self._set_status, "NFC リーダーを初期化できませんでした。")

    def _on_connect(self, tag: Tag) -> bool:
        if not isinstance(tag, FelicaStandard):
            self._async(self._show_message, "FeliCa 以外のタグを検出しました。")
            self._async(self._set_status, "FeliCa カードをかざしてください。")
            return True

        extractor = FcfDataExtractor(tag)
        try:
            data = extractor.read()
        except RuntimeError as exc:
            self._async(self._show_message, str(exc))
            self._async(self._set_status, "別のカードをかざしてください。")
            return True
        except Exception as exc:
            self._async(
                self._show_message,
                f"カード情報の取得に失敗しました: {exc}",
            )
            self._async(self._set_status, "もう一度かざしてください。")
            return True

        self._async(self._display_card_data, data)
        self._async(self._set_status, "カードを保持しています…")
        return True

    def _on_release(self, tag: Tag) -> bool:
        self._async(self._set_status, "カードを離しました。")
        self._async(self._show_message, "カードをかざしてください。")
        return True

    def _display_card_data(self, data: FcfCardData) -> None:
        self.idm_var.set(data.idm_hex)
        self.pmm_var.set(data.pmm_hex)

        for key, var in self.basic_info_vars.items():
            value = data.basic_information.get(key) or "-"
            var.set(value)

        self.fcf_un_var.set(data.fcf_un or "-")
        self._show_message("カード情報を更新しました。")

    def _set_status(self, message: str) -> None:
        self.status_var.set(message)

    def _show_message(self, message: str) -> None:
        self.message_var.set(message)

    def _async(self, func, *args) -> None:
        self.root.after(0, func, *args)

    def _on_close(self) -> None:
        self.stop_event.set()
        self.root.destroy()


def main() -> None:
    app = FcfViewerApp()
    app.run()


if __name__ == "__main__":
    main()
