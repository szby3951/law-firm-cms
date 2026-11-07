"""通用工具函数。"""


def mask_id_no(id_no: str | None) -> str | None:
    """对证件号（身份证/统一社会信用代码等）做展示脱敏。

    保留前若干位与后若干位，中间用 ``*`` 打码：
    - 长度 <= 7：只保留首尾各 1 位，其余打码（短编号也安全）
    - 长度 8~15：保留前 3 后 3
    - 长度 >= 16（18 位身份证 / 18 位统一社会信用代码）：保留前 4 后 4，
      例如 ``1101**********1234``

    空值原样返回，避免下游空指针。
    """
    if not id_no:
        return id_no

    n = len(id_no)
    if n <= 7:
        keep = 1
    elif n <= 15:
        keep = 3
    else:
        keep = 4

    if n <= keep * 2:
        # 极短时无法既留头又留尾，则只留首位
        return id_no[0] + "*" * (n - 1)

    head = id_no[:keep]
    tail = id_no[-keep:]
    return head + "*" * (n - keep * 2) + tail
