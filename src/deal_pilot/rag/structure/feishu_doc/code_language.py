"""飞书代码块 code.style.language 的语言编号。

来源：飞书 Block 数据结构的 CodeLanguage 表，核对日期 2026-10-16。
https://open.feishu.cn/document/ukTMukTMukTM/uUDN04SN0QjL1QDN/document-docx/docx-v1/data-structure/block
"""

from enum import IntEnum, unique


@unique
class CodeLanguage(IntEnum):
    """已列出的代码块语言；未知编号由调用方保留为 int，不替换成纯文本。"""

    PLAIN_TEXT = 1
    ABAP = 2
    ADA = 3
    APACHE = 4
    APEX = 5
    ASSEMBLY = 6
    BASH = 7
    C_SHARP = 8
    CPP = 9
    C = 10
    COBOL = 11
    CSS = 12
    COFFEE_SCRIPT = 13
    D = 14
    DART = 15
    DELPHI = 16
    DJANGO = 17
    DOCKERFILE = 18
    ERLANG = 19
    FORTRAN = 20
    FOX_PRO = 21
    GO = 22
    GROOVY = 23
    HTML = 24
    HTML_BARS = 25
    HTTP = 26
    HASKELL = 27
    JSON = 28
    JAVA = 29
    JAVASCRIPT = 30
    JULIA = 31
    KOTLIN = 32
    LATEX = 33
    LISP = 34
    LOGO = 35
    LUA = 36
    MATLAB = 37
    MAKEFILE = 38
    MARKDOWN = 39
    NGINX = 40
    OBJECTIVE_C = 41  # 官方枚举表简写为 Objective。
    OPEN_EDGE_ABL = 42
    PHP = 43
    PERL = 44
    POSTSCRIPT = 45
    POWER_SHELL = 46
    PROLOG = 47
    PROTOBUF = 48
    PYTHON = 49
    R = 50
    RPG = 51
    RUBY = 52
    RUST = 53
    SAS = 54
    SCSS = 55
    SQL = 56
    SCALA = 57
    SCHEME = 58
    SCRATCH = 59
    SHELL = 60
    SWIFT = 61
    THRIFT = 62
    TYPESCRIPT = 63
    VB_SCRIPT = 64
    VISUAL_BASIC = 65  # 官方枚举表简写为 Visual。
    XML = 66
    YAML = 67
    CMAKE = 68
    DIFF = 69
    GHERKIN = 70
    GRAPHQL = 71
    OPENGL_SHADING_LANGUAGE = 72
    PROPERTIES = 73
    SOLIDITY = 74
    TOML = 75
