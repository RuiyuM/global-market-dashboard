from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations, permutations
from math import log
from typing import Any, Dict, Iterable, List, Tuple, Union


ALIASES = {
    "USD": "美", "US": "美", "美元": "美", "美": "美",
    "CNY": "中", "CNH": "中", "RMB": "中", "人民币": "中", "中": "中",
    "JPY": "日", "日元": "日", "日": "日",
}


def norm_ccy(x: str) -> str:
    x = str(x).strip()
    return ALIASES.get(x.upper(), ALIASES.get(x, x))


def split_pair(pair: str) -> Tuple[str, str]:
    """
    支持：
    - "美中"
    - "美/中"
    - "美兑中"
    - "USD/CNY"
    - "USDCNY"
    """
    s = str(pair).strip()

    for sep in ["兑", "/", "-", "_", "→", "->", " "]:
        if sep in s:
            parts = [p for p in s.replace("->", sep).split(sep) if p]
            if len(parts) == 2:
                return norm_ccy(parts[0]), norm_ccy(parts[1])

    s2 = s.replace(" ", "")

    if len(s2) == 2:
        return norm_ccy(s2[0]), norm_ccy(s2[1])

    if len(s2) == 6:
        return norm_ccy(s2[:3]), norm_ccy(s2[3:])

    raise ValueError(f"无法识别货币对: {pair!r}")


@dataclass(frozen=True)
class RateChange:
    base: str
    quote: str
    old: float
    new: float


@dataclass(frozen=True)
class DirectQ:
    base: str
    quote: str
    old: float
    new: float
    q: float


@dataclass(frozen=True)
class RouteResult:
    x: str
    y: str
    z: str
    score: float
    status: str

    @property
    def label(self) -> str:
        return f"{self.x}通过{self.y}多兑换{self.z}"


def parse_rate_change(item: Union[Tuple[Any, Any, Any], Dict[str, Any]]) -> RateChange:
    """
    输入格式任选一种：

    1）("美中", 6.83, 6.82)

    2）{"pair": "美中", "old": 6.83, "new": 6.82}

    3）{"base": "美", "quote": "中", "old": 6.83, "new": 6.82}
    """
    if isinstance(item, dict):
        old = float(item["old"])
        new = float(item["new"])

        if "pair" in item:
            base, quote = split_pair(str(item["pair"]))
        else:
            base = norm_ccy(str(item["base"]))
            quote = norm_ccy(str(item["quote"]))

        return RateChange(base, quote, old, new)

    if isinstance(item, tuple) and len(item) == 3:
        base, quote = split_pair(str(item[0]))
        return RateChange(base, quote, float(item[1]), float(item[2]))

    raise TypeError("每条输入必须是 ('美中', old, new) 或 {'pair':'美中','old':old,'new':new}。")


def calc_q(old: float, new: float, method: str = "log_percent") -> float:
    """
    把汇率变化转换成口诀值 Q_AB。

    Q_AB > 0：A兑B升值
    Q_AB < 0：A兑B贬值

    method:
    - log_percent：默认。Q = 100 * ln(new / old)
      适合真实汇率，因为不同货币对的报价单位不同，必须先统一成对数百分比。
    - pct_percent：Q = 100 * (new / old - 1)
      普通百分比。
    - raw：Q = new - old
      适合你的 100 -> 95 这种作业题，得到 -5。
    """
    if old <= 0 or new <= 0:
        raise ValueError("汇率必须大于 0。")

    if method == "log_percent":
        return 100.0 * log(new / old)

    if method == "pct_percent":
        return 100.0 * (new / old - 1.0)

    if method == "raw":
        return new - old

    raise ValueError("method 只能是 'log_percent'、'pct_percent' 或 'raw'。")


def build_q_table(
    changes: Iterable[Union[Tuple[Any, Any, Any], Dict[str, Any]]],
    method: str = "log_percent",
    conflict_tol: float = 1e-9,
) -> Tuple[List[str], Dict[Tuple[str, str], float], List[DirectQ]]:

    q: Dict[Tuple[str, str], float] = {}
    currencies: List[str] = []
    direct_rows: List[DirectQ] = []

    def add_currency(c: str) -> None:
        if c not in currencies:
            currencies.append(c)

    def add_q(a: str, b: str, val: float) -> None:
        key = (a, b)

        if key in q and abs(q[key] - val) > conflict_tol:
            raise ValueError(
                f"{a}兑{b}出现重复但不一致: 已有 {q[key]:+.8f}, 新值 {val:+.8f}"
            )

        q[key] = val

    for item in changes:
        rc = parse_rate_change(item)

        add_currency(rc.base)
        add_currency(rc.quote)

        val = calc_q(rc.old, rc.new, method=method)

        direct_rows.append(
            DirectQ(
                base=rc.base,
                quote=rc.quote,
                old=rc.old,
                new=rc.new,
                q=val,
            )
        )

        # 你的口诀反向规则：
        # A兑B升值多少，B兑A就贬值多少。
        # 所以：Q_BA = -Q_AB
        add_q(rc.base, rc.quote, val)
        add_q(rc.quote, rc.base, -val)

    return currencies, q, direct_rows


def analyze_fx_logic(
    changes: Iterable[Union[Tuple[Any, Any, Any], Dict[str, Any]]],
    method: str = "log_percent",
    eps: float = 1e-9,
) -> Dict[str, Any]:
    """
    口诀检测核心：

    1. 兑看方向：Q_AB
    2. 升贬看正负：Q_AB > 0 升，Q_AB < 0 贬
    3. 通过就相加：M_X|Y|Z = Q_XY + Q_YZ
    4. 正数才成立：M > 0
    5. 成立里取最大：max(M)
    """
    currencies, q, direct_rows = build_q_table(changes, method=method)

    if len(currencies) != 3:
        raise ValueError(
            f"当前代码按三币种检测，输入应刚好包含 3 个币种；现在是 {currencies}"
        )

    routes: List[RouteResult] = []
    missing_routes = []

    for x, y, z in permutations(currencies, 3):
        if (x, y) not in q or (y, z) not in q:
            missing_routes.append((x, y, z))
            continue

        # 你的口诀核心：
        # X通过Y多兑换Z = X兑Y的口诀值 + Y兑Z的口诀值
        score = q[(x, y)] + q[(y, z)]

        if score > eps:
            status = "成立"
        elif score < -eps:
            status = "不成立"
        else:
            status = "临界/打平"

        routes.append(RouteResult(x, y, z, score, status))

    valid_routes = [r for r in routes if r.score > eps]

    best_route = max(valid_routes, key=lambda r: r.score) if valid_routes else None

    # 强弱分数：
    # Q_AB = A 相对 B 的强弱。
    # 一个币种的分数 = 它相对其他币种 Q 的平均值。
    strength = {}

    for c in currencies:
        vals = [
            q[(c, other)]
            for other in currencies
            if other != c and (c, other) in q
        ]

        strength[c] = sum(vals) / len(vals) if vals else float("nan")

    ranking = sorted(currencies, key=lambda c: strength[c], reverse=True)

    # 三角闭环残差：
    # 检查 Q_AC 是否等于 Q_AB + Q_BC。
    triangle_residuals = []

    for a, b, c in combinations(currencies, 3):
        if (a, b) in q and (b, c) in q and (a, c) in q:
            res = q[(a, c)] - (q[(a, b)] + q[(b, c)])

            triangle_residuals.append(
                {
                    "formula": f"Q_{a}{c} - (Q_{a}{b} + Q_{b}{c})",
                    "residual": res,
                    "status": "闭环一致" if abs(res) <= eps else "存在路径差",
                }
            )

    return {
        "method": method,
        "currencies": currencies,
        "q": q,
        "direct_rows": direct_rows,
        "routes": routes,
        "best_route": best_route,
        "strength": strength,
        "ranking": ranking,
        "triangle_residuals": triangle_residuals,
        "missing_routes": missing_routes,
    }


def print_report(result: Dict[str, Any], decimals: int = 5) -> None:
    eps = 10 ** (-(decimals + 2))

    def fmt(x: float) -> str:
        return f"{x:+.{decimals}f}"

    def state(qv: float) -> str:
        if qv > eps:
            return "升值"
        if qv < -eps:
            return "贬值"
        return "一定/不变"

    print("=== 1）输入汇率变化 -> 口诀值 Q ===")
    print("定义：Q_AB > 0 表示 A兑B升值；Q_AB < 0 表示 A兑B贬值。")

    for row in result["direct_rows"]:
        print(
            f"{row.base}兑{row.quote}: {row.old} -> {row.new}，"
            f"Q={fmt(row.q)}，{state(row.q)}"
        )

    print("\n=== 2）六条‘通过’路线：M = Q前段 + Q后段 ===")

    routes_sorted = sorted(result["routes"], key=lambda r: r.score, reverse=True)

    best = result["best_route"]

    for r in routes_sorted:
        mark = "✅" if r.status == "成立" else ("⚖️" if "临界" in r.status else "❌")

        tail = "  ← 所有成立里量最大" if best is not None and r == best else ""

        print(f"{mark} {r.label}: M={fmt(r.score)}，{r.status}{tail}")

    print("\n=== 3）强弱排序 ===")

    print(" > ".join(result["ranking"]))

    for c in result["ranking"]:
        print(f"{c}: 强弱分数 {fmt(result['strength'][c])}")

    print("\n=== 4）三角闭环残差 ===")

    if not result["triangle_residuals"]:
        print("缺少三条完整汇率，无法检测闭环残差。")
    else:
        for item in result["triangle_residuals"]:
            print(
                f"{item['formula']} = {fmt(item['residual'])}，"
                f"{item['status']}"
            )

    if result["missing_routes"]:
        print("\n=== 5）缺少的路线 ===")

        for x, y, z in result["missing_routes"]:
            print(f"缺少 {x}->{y} 或 {y}->{z}，无法检测 {x}通过{y}多兑换{z}")


# ===== 示例：你最开始图里的数据 =====

if __name__ == "__main__":
    changes = [
        ("美中", 6.83, 6.82),
        ("中日", 23.35, 23.31),
        ("美日", 159.50, 159.04),
    ]

    result = analyze_fx_logic(
        changes,
        method="log_percent",
        eps=1e-9,
    )

    print_report(result, decimals=5)