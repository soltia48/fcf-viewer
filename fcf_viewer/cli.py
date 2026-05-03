from collections.abc import Iterable

import nfc
from nfc.clf import RemoteTarget
from nfc.tag import Tag
from nfc.tag.tt3 import Type3TagCommandError, ServiceCode, BlockCode
from nfc.tag.tt3_sony import FelicaStandard

SYSTEM_CODE = 0xFE00

USER_TYPE_NAMES: dict[str, str] = {
    "01": "学生",
    "02": "修士",
    "03": "研究生",
    "04": "科目等履修生",
    "05": "聴講生",
    "06": "依託学生①",
    "07": "依託学生②",
    "08": "大学院・研究生",
    "11": "専任教員",
    "19": "非常勤教員",
    "21": "専任職員",
    "22": "非常勤職員",
    "28": "外部委託事業者",
    "29": "パート・アルバイト",
    "31": "卒業生",
    "32": "父母",
    "33": "その他親族",
    "39": "ゲスト",
}


def format_user_type(user_type: str) -> str:
    name = USER_TYPE_NAMES.get(user_type)
    if name is None:
        return user_type
    return f"{user_type} ({name})"


def print_section(title: str, *, leading_newline: bool = True) -> None:
    if leading_newline:
        print()
    print(title)
    print("-" * len(title))


def print_item(label: str, value: object) -> None:
    print(f"  - {label}: {value}")


class FcfTagReporter:
    """Encapsulates the various FCF information dump routines."""

    def __init__(self, tag: FelicaStandard) -> None:
        self.tag = tag

    def _read_blocks(
        self, services: Iterable[ServiceCode], blocks: Iterable[BlockCode]
    ) -> bytes:
        return self.tag.read_without_encryption(services, blocks)

    def print_basic_information(self, *, leading_newline: bool = True) -> bool:
        print_section("基本情報", leading_newline=leading_newline)

        try:
            blocks_data = self._read_blocks(
                [ServiceCode(0x006A, 0x0B)], [BlockCode(i) for i in range(4)]
            )
        except Type3TagCommandError:
            print(
                "このカードは FCF に対応していません。(サービス 0x1A8B にアクセスできません。)"
            )
            print()
            return False

        blocks_data_str = blocks_data.decode("shift_jis")

        user_type = blocks_data_str[0:2]
        print_item("利用者区分", format_user_type(user_type))

        personal_id = blocks_data_str[2:14]
        print_item("個人ID", personal_id)

        reissue_count = blocks_data_str[14]
        print_item("再発行回数", reissue_count)

        sex = blocks_data_str[15]
        print_item("性別", sex)

        name = blocks_data_str[16:32].rstrip()
        print_item("氏名", name)

        school_id_number = blocks_data_str[32:40]
        print_item("学校識別番号", school_id_number)

        issue_date = blocks_data_str[40:48]
        print_item("発行日", issue_date)

        expire_date = blocks_data_str[48:56]
        print_item("有効期限", expire_date)

        issue_company = blocks_data_str[56]
        print_item("発行事業者", issue_company)

        return True

    def print_fcf_un(self, *, leading_newline: bool = True) -> None:
        print_section("FCF-UN", leading_newline=leading_newline)
        try:
            blocks_data = self._read_blocks([ServiceCode(0x01E8, 0x0B)], [BlockCode(0)])
        except Type3TagCommandError:
            print(
                "このカードは FCF に対応していません。(サービス 0x7A0B にアクセスできません。)"
            )
            print()
            return

        fcf_un = blocks_data.decode("ascii")
        print("FCF-UN", fcf_un)


def on_startup(target: list[RemoteTarget]) -> list[RemoteTarget]:
    return target


def on_connect(tag: Tag):
    if not isinstance(tag, FelicaStandard):
        return

    try:
        polling_result = tag.polling(SYSTEM_CODE)
        if len(polling_result) != 2:
            raise RuntimeError("Invalid polling response.")
        tag.idm, tag.pmm = polling_result
    except Type3TagCommandError:
        print()
        print(
            "このカードは FCF に対応していません。(システム 0xFE00 にアクセスできません。)"
        )
        print()
        return

    print_section("カード識別")
    print_item("IDm", tag.idm.hex().upper())
    print_item("PMm", tag.pmm.hex().upper())
    print()

    reporter = FcfTagReporter(tag)
    if not reporter.print_basic_information(leading_newline=False):
        return
    reporter.print_fcf_un()
    print()


def fix_ic_code_map():
    FelicaStandard.IC_CODE_MAP[0x31] = ("RC-S???", 1, 1)


def main() -> None:
    fix_ic_code_map()

    with nfc.ContactlessFrontend("usb") as clf:
        clf.connect(
            rdwr={
                "targets": ["212F", "424F"],  # FeliCa only
                "on-startup": on_startup,
                "on-connect": on_connect,
            }
        )


if __name__ == "__main__":
    main()
