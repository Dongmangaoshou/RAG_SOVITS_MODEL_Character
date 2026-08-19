"""句子切分器 —— 低延迟对话链路第一环：把长文本切成适合 TTS 的短句。

切分策略（三级）：
1. 按句末标点（。！？!?…）切分为"块"；
2. 超过 max_len 的块按逗号（，,、；;）二次切分；
3. 二次切分后仍超过 max_len 的片段，按 max_len 硬切。

纯标准库实现，无任何第三方依赖。
"""

import re

# 默认最大句长（字符数）
DEFAULT_MAX_LEN = 30

# 句末标点：句号 / 感叹号 / 问号（中英文）/ 省略号
_SENT_END_CHARS = "。！？!?…"
# 次句标点：逗号（中英文）/ 顿号 / 分号
_COMMA_CHARS = "，,、；;"

# 第一级切分：匹配"以句末标点结尾的块"或"无句末标点的残余块"（标点随前文保留）
_SENT_BLOCK_RE = re.compile(
    r"[^" + _SENT_END_CHARS + r"]*[" + _SENT_END_CHARS + r"]+"
    r"|[^" + _SENT_END_CHARS + r"]+"
)
# 第二级切分：匹配"以逗号结尾的片段"或"无逗号的残余片段"（逗号随前文保留）
_COMMA_BLOCK_RE = re.compile(
    r"[^" + _COMMA_CHARS + r"]*[" + _COMMA_CHARS + r"]+"
    r"|[^" + _COMMA_CHARS + r"]+"
)


def _hard_split(text: str, max_len: int) -> list[str]:
    """按 max_len 硬切（步长切片），过滤纯空白片段"""
    return [
        text[i:i + max_len]
        for i in range(0, len(text), max_len)
        if text[i:i + max_len].strip()
    ]


def split_sentences(text: str, max_len: int = DEFAULT_MAX_LEN) -> list[str]:
    """将文本切分为适合 TTS 的短句列表。

    Args:
        text: 原始文本（可为空串）
        max_len: 单句最大字符数，默认 30

    Returns:
        切分后的句子列表；空输入返回空列表
    """
    if not text or not text.strip():
        return []

    sentences: list[str] = []
    for block in _SENT_BLOCK_RE.findall(text):
        block = block.strip()
        if not block:
            continue
        if len(block) <= max_len:
            sentences.append(block)
            continue
        # 超长 → 按逗号二次切分
        for piece in _COMMA_BLOCK_RE.findall(block):
            piece = piece.strip()
            if not piece:
                continue
            if len(piece) <= max_len:
                sentences.append(piece)
            else:
                # 仍超长 → 硬切
                sentences.extend(_hard_split(piece, max_len))
    return sentences
