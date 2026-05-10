import streamlit as st
import streamlit.components.v1
from tradingview_screener import Query, col
import pandas as pd
import numpy as np
import yfinance as yf
import requests
import io
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# ── 페이지 설정 & 전역 CSS ───────────────────────────────────────
st.set_page_config(page_title="주식 스캐너 v4", page_icon="📊", layout="wide")

st.markdown("""
<style>
h1 { font-size: 28px !important; }
h3 { font-size: 18px !important; }
</style>
""", unsafe_allow_html=True)

st.title("한국 주식 종목 검색기 — 장기역배열 · 일목균형 · 볼린저 스캐너")

# ── 상수 ─────────────────────────────────────────────────────────
VALID_SMA_KEYS = {'sma_mid', 'sma_long'}
NUMS           = ['①', '②']

MA_LABELS = {
    'sma_mid':  '중기 SMA',
    'sma_long': '장기 SMA',
}

def ma_name(key):
    return f"SMA{st.session_state.ma_params[key]}"

# ── 세션 상태 초기화 ─────────────────────────────────────────────
if 'ma_order' not in st.session_state or not set(st.session_state.ma_order).issubset(VALID_SMA_KEYS):
    st.session_state.ma_order = ['sma_mid', 'sma_long']

if 'close_dir' not in st.session_state or not set(st.session_state.close_dir.keys()).issubset(VALID_SMA_KEYS):
    st.session_state.close_dir = {
        'sma_mid':  'above',   # SMA224 < 종가
        'sma_long': 'below',   # 종가 < SMA448
    }

if 'ma_params' not in st.session_state or not set(st.session_state.ma_params.keys()).issubset(VALID_SMA_KEYS):
    st.session_state.ma_params = {
        'sma_mid':  224,
        'sma_long': 448,
    }

# 일목균형표 세션
if 'ichi_params' not in st.session_state:
    st.session_state.ichi_params = {'short': 18, 'mid': 52, 'long': 104}

if 'ichi_kijun_enabled' not in st.session_state:
    st.session_state.ichi_kijun_enabled = False

if 'ichi_kijun_dir' not in st.session_state:
    st.session_state.ichi_kijun_dir = None  # 'above' or 'below'

if 'ichi_span_enabled' not in st.session_state:
    st.session_state.ichi_span_enabled = False

if 'ichi_span_candle' not in st.session_state:
    st.session_state.ichi_span_candle = '1봉전'  # '1봉전' or '0봉전(현재)'

# 볼린저밴드 세션
if 'bb_enabled' not in st.session_state:
    st.session_state.bb_enabled = False

if 'bb_params' not in st.session_state:
    st.session_state.bb_params = {'period': 42, 'std': 2.0}

if 'bb_upper_dir' not in st.session_state:
    st.session_state.bb_upper_dir = None  # 'above'=상단<종가, 'below'=종가<상단, 'inside'=밴드내

if 'bb_squeeze_enabled' not in st.session_state:
    st.session_state.bb_squeeze_enabled = False

if 'bb_squeeze_days' not in st.session_state:
    st.session_state.bb_squeeze_days = 4

if 'bb_squeeze_pct' not in st.session_state:
    st.session_state.bb_squeeze_pct = 10.0

# ── 사이드바 설정 ────────────────────────────────────────────────
st.sidebar.header("🔍 검색 설정")

st.sidebar.markdown("💰 **주가 범위 (원)**")
min_price = st.sidebar.number_input("최소 금액", value=2000,  step=500,  min_value=0)
max_price = st.sidebar.number_input("최대 금액", value=30000, step=1000, min_value=0)

min_vol = st.sidebar.number_input(
    "📦 최소 거래량", value=50000, step=10000,
    help="하루 거래량 최소 기준"
)

max_workers = st.sidebar.slider(
    "⚡ 병렬 처리 수 (workers)",
    min_value=5, max_value=30, value=15, step=5,
    help="동시에 검증할 종목 수. 높을수록 빠르지만 네트워크 부하 증가."
)

# ════════════════════════════════════════════════════════════════
# ① SMA 파라미터
# ════════════════════════════════════════════════════════════════
st.sidebar.divider()
st.sidebar.markdown("**📐 이동평균 파라미터 (SMA)**")
st.sidebar.caption("버튼 클릭으로 종가 조건 설정 (재클릭 시 해제)")

order     = st.session_state.ma_order
params    = st.session_state.ma_params
close_dir = st.session_state.close_dir

for order_idx, key in enumerate(order):
    st.sidebar.markdown(
        f"<div style='font-size:12px;font-weight:700;color:#1e6f3e;margin-top:10px'>"
        f"{NUMS[order_idx]} SMA</div>",
        unsafe_allow_html=True
    )

    val = st.sidebar.number_input(
        "SMA 기간", value=params[key],
        min_value=1, key=f"num_{key}", label_visibility="collapsed"
    )
    st.session_state.ma_params[key] = val

    cur_dir  = close_dir[key]
    cur_name = f"SMA{val}"

    c_left, c_mid, c_right = st.sidebar.columns([2, 2, 2])

    with c_left:
        active_below = cur_dir == 'below'
        if st.button(
            f"{'🔴' if active_below else '⬜'} -종가",
            key=f"btn_below_{key}", use_container_width=True,
        ):
            st.session_state.close_dir[key] = None if active_below else 'below'
            st.rerun()

    with c_mid:
        st.markdown(
            f"<div style='text-align:center;padding:6px 0 2px;"
            f"font-size:12px;font-weight:700;color:#1a3a24;'>{cur_name}</div>",
            unsafe_allow_html=True
        )
        if cur_dir is not None:
            if st.button("✖ 해제", key=f"btn_clear_{key}", use_container_width=True):
                st.session_state.close_dir[key] = None
                st.rerun()

    with c_right:
        active_above = cur_dir == 'above'
        if st.button(
            f"{'🟢' if active_above else '⬜'} +종가",
            key=f"btn_above_{key}", use_container_width=True,
        ):
            st.session_state.close_dir[key] = None if active_above else 'above'
            st.rerun()

    if cur_dir == 'below':
        st.sidebar.caption(f"  ↳ 조건: 종가 < {cur_name}")
    elif cur_dir == 'above':
        st.sidebar.caption(f"  ↳ 조건: {cur_name} < 종가")

# SMA 배열 순서 ↑↓
st.sidebar.divider()
st.sidebar.markdown("**🔢 SMA 배열 순서 조정 (↑ ↓)**")

for i, key in enumerate(order):
    col_name, col_up, col_dn = st.sidebar.columns([3, 1, 1])
    with col_name:
        st.markdown(
            f"<div style='padding-top:5px;font-size:12px'>"
            f"<b>{NUMS[i]} {ma_name(key)}</b> {MA_LABELS[key]}</div>",
            unsafe_allow_html=True
        )
    with col_up:
        if i > 0:
            if st.button("↑", key=f"up_{key}_{i}", use_container_width=True):
                lst = st.session_state.ma_order
                lst[i], lst[i-1] = lst[i-1], lst[i]
                st.rerun()
    with col_dn:
        if i < len(order) - 1:
            if st.button("↓", key=f"dn_{key}_{i}", use_container_width=True):
                lst = st.session_state.ma_order
                lst[i], lst[i+1] = lst[i+1], lst[i]
                st.rerun()

# ════════════════════════════════════════════════════════════════
# ② 일목균형표
# ════════════════════════════════════════════════════════════════
st.sidebar.divider()
st.sidebar.markdown("**🌥️ 일목균형표**")

ip = st.session_state.ichi_params
c1, c2, c3 = st.sidebar.columns(3)
with c1:
    v = st.number_input("단기", value=ip['short'], min_value=1, key="ichi_short")
    st.session_state.ichi_params['short'] = v
with c2:
    v = st.number_input("중기", value=ip['mid'], min_value=1, key="ichi_mid")
    st.session_state.ichi_params['mid'] = v
with c3:
    v = st.number_input("장기", value=ip['long'], min_value=1, key="ichi_long")
    st.session_state.ichi_params['long'] = v

st.sidebar.caption(f"단기:{st.session_state.ichi_params['short']} / 중기:{st.session_state.ichi_params['mid']} / 장기:{st.session_state.ichi_params['long']}")

# 기준선 설정
st.sidebar.markdown("<div style='font-size:12px;font-weight:700;color:#1e5f8e;margin-top:8px'>📏 기준선</div>", unsafe_allow_html=True)

kijun_en = st.session_state.ichi_kijun_enabled
kijun_dir = st.session_state.ichi_kijun_dir

kc1, kc2 = st.sidebar.columns(2)
with kc1:
    if st.button(
        f"{'✅' if kijun_en else '⬜'} 기준선 적용",
        key="btn_kijun_en", use_container_width=True
    ):
        st.session_state.ichi_kijun_enabled = not kijun_en
        if not st.session_state.ichi_kijun_enabled:
            st.session_state.ichi_kijun_dir = None
        st.rerun()

if kijun_en:
    kb1, kb2, kb3 = st.sidebar.columns([2, 2, 2])
    with kb1:
        active = kijun_dir == 'below'
        if st.button(f"{'🔴' if active else '⬜'} -종가", key="btn_kijun_below", use_container_width=True):
            st.session_state.ichi_kijun_dir = None if active else 'below'
            st.rerun()
    with kb2:
        st.markdown("<div style='text-align:center;padding:6px 0;font-size:11px;font-weight:700;color:#1a3a24;'>기준선</div>", unsafe_allow_html=True)
        if kijun_dir is not None:
            if st.button("✖", key="btn_kijun_clear", use_container_width=True):
                st.session_state.ichi_kijun_dir = None
                st.rerun()
    with kb3:
        active = kijun_dir == 'above'
        if st.button(f"{'🟢' if active else '⬜'} +종가", key="btn_kijun_above", use_container_width=True):
            st.session_state.ichi_kijun_dir = None if active else 'above'
            st.rerun()

    if kijun_dir == 'above':
        st.sidebar.caption("  ↳ 조건: 기준선 < 종가")
    elif kijun_dir == 'below':
        st.sidebar.caption("  ↳ 조건: 종가 < 기준선")

# 선행스팬 설정
st.sidebar.markdown("<div style='font-size:12px;font-weight:700;color:#1e5f8e;margin-top:8px'>☁️ 선행스팬 (A/B 구름 돌파)</div>", unsafe_allow_html=True)

span_en = st.session_state.ichi_span_enabled
span_candle = st.session_state.ichi_span_candle

sc1, sc2 = st.sidebar.columns(2)
with sc1:
    if st.button(
        f"{'✅' if span_en else '⬜'} 선행스팬 적용",
        key="btn_span_en", use_container_width=True
    ):
        st.session_state.ichi_span_enabled = not span_en
        st.rerun()

if span_en:
    st.sidebar.caption("📌 선행스팬 A/B 중 높은 값(상단 구름) 기준 돌파 검색")
    sb1, sb2 = st.sidebar.columns(2)
    with sb1:
        active = span_candle == '1봉전'
        if st.button(
            f"{'🟦' if active else '⬜'} 1봉전 돌파",
            key="btn_span_1", use_container_width=True,
            help="2봉전 상단구름 > 종가 → 1봉전 상단구름 < 종가"
        ):
            st.session_state.ichi_span_candle = '1봉전'
            st.rerun()
    with sb2:
        active = span_candle == '0봉전(현재)'
        if st.button(
            f"{'🟦' if active else '⬜'} 당일 돌파",
            key="btn_span_0", use_container_width=True,
            help="1봉전 상단구름 > 종가 → 0봉전 상단구름 < 종가"
        ):
            st.session_state.ichi_span_candle = '0봉전(현재)'
            st.rerun()

    if span_candle == '1봉전':
        st.sidebar.caption("  ↳ 조건: 2봉전 상단구름 > 종가 & 1봉전 상단구름 < 종가")
    else:
        st.sidebar.caption("  ↳ 조건: 1봉전 상단구름 > 종가 & 현재 상단구름 < 종가")

# ════════════════════════════════════════════════════════════════
# ③ 볼린저밴드
# ════════════════════════════════════════════════════════════════
st.sidebar.divider()
st.sidebar.markdown("**📉 볼린저밴드**")

bb_en = st.session_state.bb_enabled
bp    = st.session_state.bb_params
bb_dir = st.session_state.bb_upper_dir
bb_sq  = st.session_state.bb_squeeze_enabled

bbc1, bbc2 = st.sidebar.columns(2)
with bbc1:
    if st.button(
        f"{'✅' if bb_en else '⬜'} 볼린저밴드 적용",
        key="btn_bb_en", use_container_width=True
    ):
        st.session_state.bb_enabled = not bb_en
        if not st.session_state.bb_enabled:
            st.session_state.bb_upper_dir = None
            st.session_state.bb_squeeze_enabled = False
        st.rerun()

if bb_en:
    bpp1, bpp2 = st.sidebar.columns(2)
    with bpp1:
        pv = st.number_input("기간", value=bp['period'], min_value=2, key="bb_period")
        st.session_state.bb_params['period'] = pv
    with bpp2:
        sv = st.number_input("승수", value=bp['std'], min_value=0.1, step=0.1, key="bb_std")
        st.session_state.bb_params['std'] = sv

    st.sidebar.caption("**상단밴드 조건**")
    bb1, bb2 = st.sidebar.columns(2)
    with bb1:
        active = bb_dir == 'above'
        if st.button(f"{'🟢' if active else '⬜'} 상단<종가", key="btn_bb_above", use_container_width=True, help="종가 > 상단밴드 (상단 돌파)"):
            st.session_state.bb_upper_dir = None if active else 'above'
            st.rerun()
    with bb2:
        active = bb_dir == 'inside'
        if st.button(f"{'🟡' if active else '⬜'} 밴드내", key="btn_bb_inside", use_container_width=True, help="하단밴드 ≤ 종가 ≤ 상단밴드"):
            st.session_state.bb_upper_dir = None if active else 'inside'
            st.rerun()

    if bb_dir == 'above':
        st.sidebar.caption("  ↳ 조건: 상단밴드 < 종가")
    elif bb_dir == 'inside':
        st.sidebar.caption("  ↳ 조건: 하단밴드 ≤ 종가 ≤ 상단밴드")

    st.sidebar.caption("**스퀴즈 조건 (AND)**")
    sq1, sq2 = st.sidebar.columns(2)
    with sq1:
        if st.button(
            f"{'✅' if bb_sq else '⬜'} 스퀴즈 적용",
            key="btn_bb_sq", use_container_width=True,
            help="상단·하단밴드가 중심선과 편차 N% 이내로 N일 이상 지속"
        ):
            st.session_state.bb_squeeze_enabled = not bb_sq
            st.rerun()

    if bb_sq:
        sqc1, sqc2 = st.sidebar.columns(2)
        with sqc1:
            dv = st.number_input("최소 일수", value=st.session_state.bb_squeeze_days, min_value=1, key="bb_sq_days")
            st.session_state.bb_squeeze_days = dv
        with sqc2:
            pct = st.number_input("편차(%)", value=st.session_state.bb_squeeze_pct, min_value=0.1, step=0.5, key="bb_sq_pct")
            st.session_state.bb_squeeze_pct = pct
        st.sidebar.caption(f"  ↳ 상단/하단이 중심선 ±{pct:.1f}% 이내 상태 {dv}일 이상")

# ── 사이드바 조건 요약 ────────────────────────────────────────────
st.sidebar.divider()
st.sidebar.markdown("**📋 현재 조건 요약**")

order     = st.session_state.ma_order
params    = st.session_state.ma_params
close_dir = st.session_state.close_dir

st.sidebar.caption(
    "SMA 배열: " + " · ".join(
        f"SMA{params[order[i]]} < SMA{params[order[i+1]]}"
        for i in range(len(order) - 1)
    )
)

close_parts = [
    (f"SMA{params[k]} < 종가" if close_dir[k] == 'above' else f"종가 < SMA{params[k]}")
    for k in order if close_dir[k] is not None
]
st.sidebar.caption("SMA 종가: " + (" · ".join(close_parts) if close_parts else "없음"))

ip2 = st.session_state.ichi_params
ichi_summary = []
if st.session_state.ichi_kijun_enabled and st.session_state.ichi_kijun_dir:
    d = st.session_state.ichi_kijun_dir
    ichi_summary.append(f"기준선{'<종가' if d=='above' else '>종가'}")
if st.session_state.ichi_span_enabled:
    ichi_summary.append(f"선행스팬 구름돌파({st.session_state.ichi_span_candle})")
st.sidebar.caption("일목: " + (" · ".join(ichi_summary) if ichi_summary else "없음"))

bb_summary = []
if st.session_state.bb_enabled:
    bp2 = st.session_state.bb_params
    bb_summary.append(f"기간{bp2['period']}/승수{bp2['std']}")
    if st.session_state.bb_upper_dir:
        d = st.session_state.bb_upper_dir
        bb_summary.append({'above':'상단<종가','inside':'밴드내','below':'종가<상단'}[d])
    if st.session_state.bb_squeeze_enabled:
        bb_summary.append(f"스퀴즈{st.session_state.bb_squeeze_days}일/{st.session_state.bb_squeeze_pct:.0f}%")
st.sidebar.caption("볼린저: " + (" · ".join(bb_summary) if bb_summary else "없음"))


# ── 메인: 현재 조건 요약 ─────────────────────────────────────────
order     = st.session_state.ma_order
params    = st.session_state.ma_params
close_dir = st.session_state.close_dir
close_parts = [
    (f"**SMA{params[k]} < 종가**" if close_dir[k] == 'above' else f"**종가 < SMA{params[k]}**")
    for k in order if close_dir[k] is not None
]

ip3 = st.session_state.ichi_params
kijun_mid = ip3['mid']

ichi_lines = []
if st.session_state.ichi_kijun_enabled and st.session_state.ichi_kijun_dir:
    d = st.session_state.ichi_kijun_dir
    ichi_lines.append(f"기준선(중기{kijun_mid}) {'<' if d=='above' else '>'} 종가")
if st.session_state.ichi_span_enabled:
    ichi_lines.append(f"선행스팬 A/B 상단구름 돌파 ({st.session_state.ichi_span_candle})")

bb_lines = []
bp3 = st.session_state.bb_params
if st.session_state.bb_enabled:
    bb_lines.append(f"기간 {bp3['period']} / 승수 {bp3['std']}")
    if st.session_state.bb_upper_dir:
        d = st.session_state.bb_upper_dir
        bb_lines.append({'above':'상단밴드 < 종가','inside':'하단밴드 ≤ 종가 ≤ 상단밴드','below':'종가 < 상단밴드'}[d])
    if st.session_state.bb_squeeze_enabled:
        bb_lines.append(f"스퀴즈: 편차 {st.session_state.bb_squeeze_pct:.0f}% 이내 {st.session_state.bb_squeeze_days}일 이상 (AND)")

st.markdown(f"""
**검색 조건 (일봉 기준)**
- 📊 **SMA 배열**: {' · '.join(f"**SMA{params[order[i]]}** < **SMA{params[order[i+1]]}**" for i in range(len(order)-1))}
- 🎯 **SMA 종가**: {' · '.join(close_parts) if close_parts else '없음'}
- 🌥️ **일목균형표**: {' · '.join(ichi_lines) if ichi_lines else '없음'}
- 📉 **볼린저밴드**: {' · '.join(bb_lines) if bb_lines else '없음 (비활성)'}
- 💰 **주가**: {min_price:,}원 ~ {max_price:,}원 · 거래량 {min_vol:,} 이상
- 🚫 ETF · 스팩 · 우선주 · 거래정지 · 투자경고 · 관리종목 · 환기종목 자동 제외
""")


# ── KRX 종목 목록 & 제재종목 로딩 ───────────────────────────────
@st.cache_data(ttl=3600)
def load_krx_data():
    name_map       = {}
    exclude_set    = set()
    sanction_codes = set()

    try:
        resp = requests.get(
            "https://kind.krx.co.kr/corpgeneral/corpList.do",
            params={"method": "download", "searchType": "13"},
            headers={"User-Agent": "Mozilla/5.0"}, timeout=10
        )
        resp.encoding = 'euc-kr'
        df = pd.read_html(io.StringIO(resp.text))[0]
        df.columns = df.columns.str.strip()

        code_col = next((c for c in df.columns if '종목코드' in c or '코드' in c), None)
        name_col = next((c for c in df.columns if '회사명' in c or '종목명' in c or '기업명' in c), None)

        if code_col and name_col:
            df[code_col] = df[code_col].astype(str).str.zfill(6)
            name_map = dict(zip(df[code_col], df[name_col]))

            exclude_keywords = ['스팩', 'SPAC', '리츠', 'REIT', '인프라', '환기',
                                '수익증권', 'ETF', 'ETN', 'ELW']
            for _, row in df.iterrows():
                code = str(row[code_col]).zfill(6)
                name = str(row[name_col])
                if not code.endswith('0') or any(kw in name.upper() for kw in exclude_keywords):
                    exclude_set.add(code)

    except Exception as e:
        st.warning(f"KRX 종목 목록 로딩 실패 ({e}).")

    sanction_urls = [
        {"url": "https://kind.krx.co.kr/investwarning/managementissue.do",
         "params": {"method": "searchManagementIssueSub", "marketType": "0"}},
        {"url": "https://kind.krx.co.kr/investwarning/investwarning.do",
         "params": {"method": "searchInvestWarningSub", "marketType": "0"}},
        {"url": "https://kind.krx.co.kr/investwarning/tradesuspend.do",
         "params": {"method": "searchTradeSuspendSub", "marketType": "0"}},
        {"url": "https://kind.krx.co.kr/investwarning/unfaithfuldisclosure.do",
         "params": {"method": "searchUnfaithfulDisclosureSub", "marketType": "0"}},
    ]

    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://kind.krx.co.kr/"}
    rev_map = {v: k for k, v in name_map.items()}

    for item in sanction_urls:
        try:
            resp = requests.get(item["url"], params=item["params"], headers=headers, timeout=10)
            resp.encoding = 'euc-kr'
            tables = pd.read_html(io.StringIO(resp.text))
            if not tables:
                continue
            tbl = tables[0]
            tbl.columns = tbl.columns.str.strip()

            code_col = next((c for c in tbl.columns if '종목코드' in c or '단축코드' in c or '코드' in c), None)
            if code_col:
                tbl[code_col] = tbl[code_col].astype(str).str.zfill(6)
                sanction_codes.update(tbl[code_col])
            else:
                name_col2 = next((c for c in tbl.columns if '종목명' in c or '회사명' in c), None)
                if name_col2:
                    for nm in tbl[name_col2].dropna():
                        cd = rev_map.get(str(nm).strip())
                        if cd:
                            sanction_codes.add(cd)
        except Exception:
            continue

    return name_map, exclude_set, sanction_codes


# ── 재무 데이터 ──────────────────────────────────────────────────
@st.cache_data(ttl=3600, show_spinner=False)
def get_financial_history(code_6: str):
    for suffix in ['.KS', '.KQ']:
        try:
            tk  = yf.Ticker(f"{code_6}{suffix}")
            inc = tk.quarterly_income_stmt
            op_series = pd.Series(dtype=float)

            if inc is not None and not inc.empty:
                for label in ['Operating Income', 'EBIT', 'Operating Revenue']:
                    if label in inc.index:
                        raw = inc.loc[label].dropna()
                        if not raw.empty:
                            raw.index = pd.to_datetime(raw.index)
                            raw = raw.sort_index().tail(6) / 1e8
                            raw.index = [d.strftime('%Y.%m') for d in raw.index]
                            op_series = raw
                            break

            bal = tk.quarterly_balance_sheet
            debt_series = pd.Series(dtype=float)

            if bal is not None and not bal.empty:
                total_liab = next(
                    (bal.loc[l].dropna() for l in ['Total Liabilities Net Minority Interest', 'Total Liabilities'] if l in bal.index),
                    None
                )
                equity = next(
                    (bal.loc[l].dropna() for l in ['Stockholders Equity', 'Total Equity Gross Minority Interest', 'Common Stock Equity'] if l in bal.index),
                    None
                )
                if total_liab is not None and equity is not None:
                    total_liab.index = pd.to_datetime(total_liab.index)
                    equity.index     = pd.to_datetime(equity.index)
                    common_idx = total_liab.index.intersection(equity.index).sort_values()
                    if len(common_idx) > 0:
                        ratio = (total_liab[common_idx] / equity[common_idx] * 100).dropna().tail(6)
                        ratio.index = [d.strftime('%Y.%m') for d in ratio.index]
                        debt_series = ratio

            if not op_series.empty or not debt_series.empty:
                return op_series, debt_series

        except Exception:
            continue

    return pd.Series(dtype=float), pd.Series(dtype=float)


# ── 업종 정보 ────────────────────────────────────────────────────
@st.cache_data(ttl=3600, show_spinner=False)
def get_sector_info(code_6: str):
    for suffix in ['.KS', '.KQ']:
        try:
            info = yf.Ticker(f"{code_6}{suffix}").info
            if info.get('sector') or info.get('industry'):
                return {
                    'sector':    info.get('sector',             '-'),
                    'industry':  info.get('industry',           '-'),
                    'employees': info.get('fullTimeEmployees',   None),
                    'summary':   info.get('longBusinessSummary', None),
                }
        except Exception:
            continue
    return None


# ── 재무 차트 렌더링 ─────────────────────────────────────────────
def render_financial_chart(name: str, code: str, op_series: pd.Series, debt_series: pd.Series):
    if op_series.empty and debt_series.empty:
        st.warning(f"{name} — 재무 데이터를 가져올 수 없습니다.")
        return

    quarters      = sorted(set(op_series.index.tolist() + debt_series.index.tolist()))
    op_vals       = [round(float(op_series[q]),   1) if q in op_series.index   else None for q in quarters]
    debt_vals_raw = [round(float(debt_series[q]), 1) if q in debt_series.index else None for q in quarters]
    chart_id      = f"chart_{code}"

    html = f"""
<div style="background:linear-gradient(160deg,#d4edda 0%,#e8f5e9 40%,#f0faf1 100%);
            border-radius:12px;padding:20px 20px 16px;font-family:'Malgun Gothic',sans-serif;">
  <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">
    <div style="width:13px;height:13px;background:#2d6a3f;border-radius:2px;"></div>
    <span style="font-size:14px;font-weight:700;color:#1a3a24;">{name} ({code}) — 분기별 재무 추이</span>
  </div>
  <div style="display:flex;justify-content:space-between;font-size:11px;font-weight:700;margin-bottom:2px;padding:0 4px;">
    <span style="color:#2d7a4a;">억원</span>
    <span style="color:#b05010;">%</span>
  </div>
  <div style="position:relative;height:290px;"><canvas id="{chart_id}"></canvas></div>
  <div id="info_{chart_id}"
       style="min-height:36px;margin:8px 0 6px;padding:8px 14px;
              background:rgba(30,111,62,0.08);border-radius:8px;
              font-size:13px;font-weight:600;color:#1a3a24;
              border-left:3px solid #2d7a4a;display:flex;
              align-items:center;flex-wrap:wrap;gap:8px;">
    <span style="color:#888;font-weight:400;font-size:12px;">막대를 탭/클릭하면 수치가 표시됩니다</span>
  </div>
  <div style="display:flex;flex-direction:column;gap:4px;margin-top:6px;font-size:11px;color:#444;">
    <span><span style="width:12px;height:10px;background:#3a9e5f;border-radius:2px;display:inline-block;margin-right:5px;vertical-align:middle;"></span>영업이익 (+억원)</span>
    <span><span style="width:12px;height:10px;background:#c0392b;border-radius:2px;display:inline-block;margin-right:5px;vertical-align:middle;"></span>영업이익 (-억원)</span>
    <span><span style="width:12px;height:10px;background:#e07010;border-radius:2px;display:inline-block;margin-right:5px;vertical-align:middle;"></span>부채비율 (%)</span>
  </div>
</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<script>
(function() {{
  const quarters={json.dumps(quarters)};
  const opVals={json.dumps(op_vals)};
  const debtValsRaw={json.dumps(debt_vals_raw)};
  const ctx=document.getElementById('{chart_id}');
  const infoPanel=document.getElementById('info_{chart_id}');
  if(!ctx)return;

  function showInfo(i) {{
    const q=quarters[i], op=opVals[i], dt=debtValsRaw[i];
    let html=`<span style="color:#2d7a4a;font-weight:700;">${{q}}</span>`;
    if(op!==null) html+=`&nbsp;&nbsp;<span style="color:${{op>=0?'#1a5c30':'#c0392b'}};">영업이익: ${{op.toLocaleString()}}억원</span>`;
    if(dt!==null) html+=`&nbsp;&nbsp;<span style="color:#8a3d00;">부채비율: ${{dt.toFixed(1)}}%</span>`;
    infoPanel.innerHTML=html;
  }}

  const chartInst=new Chart(ctx,{{
    data:{{labels:quarters,datasets:[{{type:'bar',data:opVals,backgroundColor:'transparent',borderWidth:0,yAxisID:'yLeft'}}]}},
    options:{{
      responsive:true,maintainAspectRatio:false,
      plugins:{{legend:{{display:false}},tooltip:{{enabled:false}}}},
      scales:{{
        x:{{grid:{{display:false}},ticks:{{color:'transparent',font:{{size:11}}}},border:{{display:false}}}},
        yLeft:{{type:'linear',position:'left',ticks:{{color:'#2d7a4a',font:{{size:11}},callback:v=>v.toLocaleString()}},
          grid:{{color:c=>c.tick.value===0?'rgba(0,0,0,0.6)':'rgba(180,200,180,0.35)',lineWidth:c=>c.tick.value===0?2:1}},border:{{display:false}}}}
      }},
      layout:{{padding:{{top:28,bottom:32}}}},
      interaction:{{mode:'index',intersect:false}},
      onClick(e,elements){{ if(elements&&elements.length>0) showInfo(elements[0].index); }}
    }},
    plugins:[{{
      id:'cd_{code}',
      afterDraw(chart){{
        const ctx=chart.ctx,xScale=chart.scales.x,yLeft=chart.scales.yLeft;
        ctx.save();
        const zeroY=yLeft.getPixelForValue(0);
        const chartH=chart.chartArea.bottom-chart.chartArea.top;
        const maxDebt=Math.max(...debtValsRaw.filter(v=>v!==null),1);
        const debtPPU=(chartH*0.38)/maxDebt;
        const dummyMeta=chart.getDatasetMeta(0);
        const fullBarW=dummyMeta.data.length>0?dummyMeta.data[0].width:24;

        function drawBar(cx,w,top,bot,color){{
          const h=Math.abs(bot-top);if(h<1)return;
          const r=Math.min(4,h/2),yTop=Math.min(top,bot),yBot=Math.max(top,bot);
          ctx.beginPath();
          if(top>bot){{ctx.moveTo(cx-w/2,yBot);ctx.lineTo(cx+w/2,yBot);ctx.lineTo(cx+w/2,yTop+r);ctx.quadraticCurveTo(cx+w/2,yTop,cx+w/2-r,yTop);ctx.lineTo(cx-w/2+r,yTop);ctx.quadraticCurveTo(cx-w/2,yTop,cx-w/2,yTop+r);ctx.lineTo(cx-w/2,yBot);}}
          else{{ctx.moveTo(cx-w/2,yTop);ctx.lineTo(cx+w/2,yTop);ctx.lineTo(cx+w/2,yBot-r);ctx.quadraticCurveTo(cx+w/2,yBot,cx+w/2-r,yBot);ctx.lineTo(cx-w/2+r,yBot);ctx.quadraticCurveTo(cx-w/2,yBot,cx-w/2,yBot-r);ctx.lineTo(cx-w/2,yTop);}}
          ctx.closePath();ctx.fillStyle=color;ctx.fill();
        }}

        quarters.forEach((q,i)=>{{
          const opVal=opVals[i],dbtVal=debtValsRaw[i],xC=xScale.getPixelForValue(i);
          const overlap=(opVal!==null&&opVal<0&&dbtVal!==null);
          const opW=overlap?fullBarW/2-1:fullBarW*0.72;
          const dbtW=overlap?fullBarW/2-1:fullBarW*0.72;
          const opCX=overlap?xC-fullBarW/4-1:xC;
          const dbtCX=overlap?xC+fullBarW/4+1:xC;
          if(opVal!==null){{const opTop=opVal>=0?yLeft.getPixelForValue(opVal):zeroY;const opBot=opVal>=0?zeroY:yLeft.getPixelForValue(opVal);drawBar(opCX,opW,opTop,opBot,opVal>=0?'#3a9e5f':'#c0392b');}}
          if(dbtVal!==null){{drawBar(dbtCX,dbtW,zeroY,zeroY+dbtVal*debtPPU,'rgba(224,112,16,0.88)');}}
        }});

        ctx.textAlign='center';
        quarters.forEach((q,i)=>{{
          const opVal=opVals[i],dbtVal=debtValsRaw[i],xC=xScale.getPixelForValue(i);
          const overlap=(opVal!==null&&opVal<0&&dbtVal!==null);
          const opCX=overlap?xC-fullBarW/4-1:xC;
          const dbtCX=overlap?xC+fullBarW/4+1:xC;
          if(opVal!==null){{const barTop=opVal>=0?yLeft.getPixelForValue(opVal):zeroY;const barBot=opVal>=0?zeroY:yLeft.getPixelForValue(opVal);const barH=Math.abs(barBot-barTop);ctx.font="bold 10px 'Malgun Gothic',sans-serif";if(barH>22){{ctx.fillStyle='#ffffff';ctx.fillText(opVal.toLocaleString(),opCX,opVal>=0?barTop+14:barBot-6);}}else{{ctx.fillStyle=opVal<0?'#8a1a10':'#1a5c30';ctx.fillText(opVal.toLocaleString(),opCX,opVal>=0?barTop-5:barBot+13);}}}}
          if(dbtVal!==null){{const dbtBot=zeroY+dbtVal*debtPPU;const barH=Math.abs(dbtBot-zeroY);ctx.font="bold 10px 'Malgun Gothic',sans-serif";if(barH>22){{ctx.fillStyle='#ffffff';ctx.fillText(dbtVal.toFixed(1)+'%',dbtCX,dbtBot-5);}}else{{ctx.fillStyle='#8a3d00';ctx.fillText(dbtVal.toFixed(1)+'%',dbtCX,dbtBot+13);}}}}
        }});

        ctx.beginPath();ctx.moveTo(chart.chartArea.left,zeroY);ctx.lineTo(chart.chartArea.right,zeroY);ctx.strokeStyle='rgba(0,0,0,0.75)';ctx.lineWidth=2;ctx.stroke();
        ctx.beginPath();ctx.moveTo(chart.chartArea.left,chart.chartArea.top);ctx.lineTo(chart.chartArea.left,chart.chartArea.bottom);ctx.strokeStyle='rgba(0,0,0,0.5)';ctx.lineWidth=1.5;ctx.stroke();
        ctx.beginPath();ctx.moveTo(chart.chartArea.right,chart.chartArea.top);ctx.lineTo(chart.chartArea.right,chart.chartArea.bottom);ctx.strokeStyle='rgba(0,0,0,0.5)';ctx.lineWidth=1.5;ctx.stroke();

        const yBottom=chart.chartArea.bottom;
        ctx.fillStyle='#445544';ctx.fillRect(chart.chartArea.left,yBottom+2,chart.chartArea.width,24);
        ctx.font="bold 10px 'Malgun Gothic',sans-serif";ctx.textAlign='center';ctx.fillStyle='#fff';
        quarters.forEach((q,i)=>{{ctx.fillText(q,xScale.getPixelForValue(i),yBottom+17);}});
        ctx.restore();
      }}
    }}]
  }});

  document.getElementById('{chart_id}').addEventListener('touchstart',function(e){{
    e.preventDefault();
    const touch=e.touches[0];
    const elements=chartInst.getElementsAtEventForMode({{clientX:touch.clientX,clientY:touch.clientY,target:this}},'index',{{intersect:false}},true);
    if(elements&&elements.length>0) showInfo(elements[0].index);
  }},{{passive:false}});
}})();
</script>"""
    st.components.v1.html(html, height=520, scrolling=False)


# ── TradingView 전체 종목 수집 ───────────────────────────────────
def run_tv_scanner_full():
    all_rows, offset, batch = [], 0, 1500
    while True:
        try:
            result = (
                Query()
                .set_markets("korea")
                .select('name', 'close', 'volume', 'change', 'SMA200', 'price_52_week_high')
                .where(col('type') == 'stock')
                .offset(offset).limit(batch)
                .get_scanner_data()
            )
            if result is None:
                break
            count, data = result
            if data is None or data.empty:
                break
            all_rows.append(data)
            fetched = len(data)
            if fetched < batch:
                break
            offset += fetched
            time.sleep(0.5)
        except TypeError:
            break
        except Exception as e:
            st.warning(f"TradingView 수집 중단 (offset={offset}): {e}")
            break
    return pd.concat(all_rows, ignore_index=True) if all_rows else pd.DataFrame()


def apply_price_volume_filter(data, min_price, max_price, min_vol):
    mask = (data['close'] >= min_price) & (data['close'] <= max_price) & (data['volume'] > min_vol)
    return data[mask].copy()


# ── 일목균형표 계산 헬퍼 ─────────────────────────────────────────
def calc_ichimoku(high: pd.Series, low: pd.Series, close: pd.Series, short: int, mid: int, long: int):
    """
    현재 봉 위치의 구름값(선행스팬A/B)을 반환.
    선행스팬은 mid일 앞에 표시되므로 현재 위치의 구름 = mid봉 전에 계산된 값.
    즉, shift(-mid) 없이 index 그대로 사용 (현재봉 위치 기준).
    """
    def midpoint(p, n):
        return (p.rolling(n).max() + p.rolling(n).min()) / 2

    tenkan  = midpoint(high, short)   # 전환선
    kijun   = midpoint(high, mid)     # 기준선
    span_a  = (tenkan + kijun) / 2    # 선행스팬A (shift 없이 현재봉 기준)
    span_b  = midpoint(high, long)    # 선행스팬B (shift 없이 현재봉 기준)

    return kijun, span_a, span_b


# ── 볼린저밴드 계산 헬퍼 ─────────────────────────────────────────
def calc_bollinger(close: pd.Series, period: int, std_mult: float):
    sma    = close.rolling(period).mean()
    std    = close.rolling(period).std()
    upper  = sma + std_mult * std
    lower  = sma - std_mult * std
    return upper, sma, lower


def check_bb_squeeze(upper: pd.Series, lower: pd.Series, sma: pd.Series,
                     pct_threshold: float, min_days: int) -> bool:
    """
    상단밴드와 하단밴드가 각각 중심선(SMA)과의 편차가 pct_threshold% 이내인
    상태가 최근 min_days일 이상 연속으로 지속되는지 확인.
    """
    upper_pct = ((upper - sma) / sma * 100).abs()
    lower_pct = ((lower - sma) / sma * 100).abs()
    squeeze   = (upper_pct <= pct_threshold) & (lower_pct <= pct_threshold)

    # 최근 min_days 봉이 모두 squeeze 상태인지 확인
    if len(squeeze) < min_days:
        return False
    return squeeze.iloc[-min_days:].all()


# ── 전체 조건 검증 ───────────────────────────────────────────────
def check_all_conditions(code_6, ma_order, ma_params, close_dir,
                         ichi_params, ichi_kijun_enabled, ichi_kijun_dir,
                         ichi_span_enabled, ichi_span_candle,
                         bb_enabled, bb_params, bb_upper_dir,
                         bb_squeeze_enabled, bb_squeeze_days, bb_squeeze_pct):

    max_sma    = max(ma_params[k] for k in ma_order)
    ichi_long  = ichi_params['long']
    bb_period  = bb_params['period'] if bb_enabled else 0
    need_days  = max(max_sma, ichi_long, bb_period) + 60

    for suffix in ['.KS', '.KQ']:
        try:
            df = yf.download(
                f"{code_6}{suffix}",
                period=f"{need_days + 100}d",
                interval="1d",
                auto_adjust=True,
                progress=False
            )
            if df is None or len(df) < need_days:
                continue
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df = df.dropna(subset=['Close'])
            if len(df) < need_days:
                continue

            close = df['Close']
            high  = df['High']
            low   = df['Low']

            curr_close = float(close.iloc[-1])

            # ── SMA 조건 ──
            ma_vals = {key: float(close.rolling(ma_params[key]).mean().iloc[-1]) for key in ma_order}

            cond_sma_order = all(
                ma_vals[ma_order[i]] < ma_vals[ma_order[i+1]]
                for i in range(len(ma_order) - 1)
            )
            cond_sma_close = all(
                (ma_vals[k] < curr_close if close_dir[k] == 'above' else ma_vals[k] > curr_close)
                for k in ma_order if close_dir[k] is not None
            )

            if not (cond_sma_order and cond_sma_close):
                return False, curr_close, ma_vals, {}

            # ── 일목균형표 ──
            extra_vals = {}
            kijun, span_a, span_b = calc_ichimoku(
                high, low, close,
                ichi_params['short'], ichi_params['mid'], ichi_params['long']
            )

            if ichi_kijun_enabled and ichi_kijun_dir is not None:
                kijun_val = float(kijun.iloc[-1])
                extra_vals['기준선'] = round(kijun_val, 0)
                if ichi_kijun_dir == 'above' and not (kijun_val < curr_close):
                    return False, curr_close, ma_vals, extra_vals
                if ichi_kijun_dir == 'below' and not (kijun_val > curr_close):
                    return False, curr_close, ma_vals, extra_vals

            if ichi_span_enabled:
                # 현재봉 위치의 구름값
                # span_a, span_b 시리즈에서 인덱스 기준으로 봉 선택
                def upper_cloud(idx):
                    a = float(span_a.iloc[idx])
                    b = float(span_b.iloc[idx])
                    return max(a, b)

                def close_at(idx):
                    return float(close.iloc[idx])

                if ichi_span_candle == '1봉전':
                    # 2봉전 상단구름 > 종가(2봉전) AND 1봉전 상단구름 < 종가(1봉전)
                    cond_span = (
                        upper_cloud(-3) > close_at(-3) and
                        upper_cloud(-2) < close_at(-2)
                    )
                else:
                    # 1봉전 상단구름 > 종가(1봉전) AND 현재 상단구름 < 현재가
                    cond_span = (
                        upper_cloud(-2) > close_at(-2) and
                        upper_cloud(-1) < close_at(-1)
                    )

                extra_vals['선행스팬A'] = round(float(span_a.iloc[-1]), 0)
                extra_vals['선행스팬B'] = round(float(span_b.iloc[-1]), 0)

                if not cond_span:
                    return False, curr_close, ma_vals, extra_vals

            # ── 볼린저밴드 ──
            if bb_enabled:
                upper_bb, sma_bb, lower_bb = calc_bollinger(
                    close, bb_params['period'], bb_params['std']
                )
                upper_val = float(upper_bb.iloc[-1])
                lower_val = float(lower_bb.iloc[-1])
                sma_val   = float(sma_bb.iloc[-1])

                extra_vals['BB상단'] = round(upper_val, 0)
                extra_vals['BB중심'] = round(sma_val, 0)
                extra_vals['BB하단'] = round(lower_val, 0)

                if bb_upper_dir == 'above' and not (upper_val < curr_close):
                    return False, curr_close, ma_vals, extra_vals
                elif bb_upper_dir == 'inside' and not (lower_val <= curr_close <= upper_val):
                    return False, curr_close, ma_vals, extra_vals

                if bb_squeeze_enabled:
                    sq = check_bb_squeeze(upper_bb, lower_bb, sma_bb, bb_squeeze_pct, bb_squeeze_days)
                    if not sq:
                        return False, curr_close, ma_vals, extra_vals

            return True, curr_close, ma_vals, extra_vals

        except Exception:
            continue

    return False, None, {}, {}


def check_one(row_tuple, ma_order, ma_params, close_dir,
              ichi_params, ichi_kijun_enabled, ichi_kijun_dir,
              ichi_span_enabled, ichi_span_candle,
              bb_enabled, bb_params, bb_upper_dir,
              bb_squeeze_enabled, bb_squeeze_days, bb_squeeze_pct):
    idx, row = row_tuple
    result = check_all_conditions(
        row['종목코드'], ma_order, ma_params, close_dir,
        ichi_params, ichi_kijun_enabled, ichi_kijun_dir,
        ichi_span_enabled, ichi_span_candle,
        bb_enabled, bb_params, bb_upper_dir,
        bb_squeeze_enabled, bb_squeeze_days, bb_squeeze_pct
    )
    return idx, row, result


def get_chart_url(ticker_raw):
    symbol = ticker_raw if ":" in str(ticker_raw) else f"KRX:{ticker_raw}"
    return f"https://www.tradingview.com/chart/?symbol={symbol}"


# ── 메인 실행 ────────────────────────────────────────────────────
if st.button("🔍 종목 검색 시작", use_container_width=True):
    if min_price >= max_price:
        st.error("⚠️ 최소 금액이 최대 금액보다 작아야 합니다.")
    else:
        # 검색 시점 스냅샷
        ma_order_snap  = list(st.session_state.ma_order)
        ma_params_snap = dict(st.session_state.ma_params)
        close_dir_snap = dict(st.session_state.close_dir)
        ichi_params_snap       = dict(st.session_state.ichi_params)
        ichi_kijun_enabled_snap = st.session_state.ichi_kijun_enabled
        ichi_kijun_dir_snap    = st.session_state.ichi_kijun_dir
        ichi_span_enabled_snap = st.session_state.ichi_span_enabled
        ichi_span_candle_snap  = st.session_state.ichi_span_candle
        bb_enabled_snap        = st.session_state.bb_enabled
        bb_params_snap         = dict(st.session_state.bb_params)
        bb_upper_dir_snap      = st.session_state.bb_upper_dir
        bb_squeeze_enabled_snap = st.session_state.bb_squeeze_enabled
        bb_squeeze_days_snap   = st.session_state.bb_squeeze_days
        bb_squeeze_pct_snap    = st.session_state.bb_squeeze_pct

        with st.spinner("📋 KRX 종목 정보 및 제재종목 로딩 중..."):
            name_map, exclude_set, sanction_codes = load_krx_data()

        all_excluded = exclude_set | sanction_codes
        st.info(f"🚫 제외: ETF·스팩·우선주 {len(exclude_set)}개 + 제재종목 {len(sanction_codes)}개 = {len(all_excluded)}개")

        with st.spinner("🔍 TradingView 전체 종목 수집 중..."):
            data = run_tv_scanner_full()

        if data is None or data.empty:
            st.warning("⚠️ TradingView에서 종목을 가져오지 못했습니다.")
        else:
            total_tv = len(data)
            data['종목코드'] = data['name'].apply(lambda x: str(x).split(':')[-1]).str.zfill(6)
            data = apply_price_volume_filter(data, min_price, max_price, min_vol)
            after_price = len(data)

            data = data[~data['종목코드'].isin(all_excluded)]
            after_sanction = len(data)

            data['종목명'] = data['종목코드'].map(name_map).fillna(
                data['name'].apply(lambda x: str(x).split(':')[-1])
            )

            etf_pattern = r'ETF|ETN|KODEX|TIGER|RISE|ACE|KBSTAR|HANARO|ARIRANG|SOL|KOSEF'
            data = data[data['종목명'].notna()]
            data = data[~data['종목명'].str.contains(etf_pattern, case=False, na=False)]
            after_etf = len(data)

            st.info(
                f"📊 수집: {total_tv}개 → 주가·거래량: {after_price}개 "
                f"→ 제재·ETF 제외: {after_sanction}개 → ETF패턴: {after_etf}개 "
                f"→ **조건 검증 시작** (병렬 {max_workers}workers)"
            )

            progress_bar = st.progress(0)
            status_text  = st.empty()
            results      = []
            total        = len(data)
            done_count   = 0

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(
                        check_one, row_tuple,
                        ma_order_snap, ma_params_snap, close_dir_snap,
                        ichi_params_snap, ichi_kijun_enabled_snap, ichi_kijun_dir_snap,
                        ichi_span_enabled_snap, ichi_span_candle_snap,
                        bb_enabled_snap, bb_params_snap, bb_upper_dir_snap,
                        bb_squeeze_enabled_snap, bb_squeeze_days_snap, bb_squeeze_pct_snap
                    ): row_tuple
                    for row_tuple in data.iterrows()
                }
                for future in as_completed(futures):
                    done_count += 1
                    progress_bar.progress(done_count / total)
                    try:
                        idx, row, (pass_all, curr_close, ma_vals, extra_vals) = future.result()
                    except Exception:
                        status_text.text(f"⚡ [{done_count}/{total}] 검증 중...")
                        continue

                    status_text.text(f"⚡ [{done_count}/{total}] {row['종목명']}({row['종목코드']}) 검증 완료")

                    if pass_all:
                        entry = {
                            '종목명':      row['종목명'],
                            '종목코드':    row['종목코드'],
                            '현재가(원)':  row['close'],
                            '거래량':      row['volume'],
                            '등락률(%)':   row['change'],
                            '52주 신고가': row.get('price_52_week_high', None),
                            'name_raw':    row['name'],
                        }
                        for key in ma_order_snap:
                            entry[f"SMA{ma_params_snap[key]}"] = round(ma_vals[key], 0) if key in ma_vals else None
                        entry.update(extra_vals)
                        results.append(entry)

            progress_bar.empty()
            status_text.empty()

            if not results:
                st.warning("⚠️ 모든 조건을 만족하는 종목이 없습니다. 조건을 완화해 보세요.")
            else:
                st.success(f"✅ 최종 {len(results)}개 종목 발견!")
                result_df = pd.DataFrame(results)

                ma_cols      = [f"SMA{ma_params_snap[k]}" for k in ma_order_snap]
                extra_cols   = [c for c in ['기준선', '선행스팬A', '선행스팬B', 'BB상단', 'BB중심', 'BB하단'] if c in result_df.columns]
                display_cols = ['종목명', '종목코드', '현재가(원)', '거래량', '등락률(%)'] + ma_cols + extra_cols + ['52주 신고가']
                display_cols = [c for c in display_cols if c in result_df.columns]
                display      = result_df[display_cols].copy()

                fmt = {'현재가(원)': '{:,.0f}', '거래량': '{:,.0f}', '등락률(%)': '{:+.2f}', '52주 신고가': '{:,.0f}'}
                fmt.update({c: '{:,.0f}' for c in ma_cols + extra_cols if c in display.columns})
                st.dataframe(display.style.format(fmt, na_rep="-"), use_container_width=True, hide_index=True)

                # ── 분기 재무 추이 ──
                st.divider()
                st.subheader("📉 종목별 분기 재무 추이 (영업이익 · 부채비율)")
                st.caption("yfinance 분기별 재무제표 기준 | 영업이익: 억 원 | 부채비율 = 총부채 ÷ 자기자본 × 100")

                tabs = st.tabs([r['종목명'] for r in results[:20]])
                for tab, row in zip(tabs, results[:20]):
                    with tab:
                        code = row['종목코드']
                        name = row['종목명']
                        with st.spinner(f"{name} 재무 데이터 조회 중..."):
                            op_series, debt_series = get_financial_history(code)

                        c1, c2 = st.columns(2)
                        with c1:
                            if not op_series.empty:
                                latest_op = op_series.iloc[-1]
                                delta_op  = (op_series.iloc[-1] - op_series.iloc[-2]) if len(op_series) >= 2 else None
                                st.metric("최근 분기 영업이익", f"{latest_op:,.0f} 억원",
                                          delta=f"{delta_op:+,.0f} 억원" if delta_op is not None else None,
                                          delta_color="normal")
                            else:
                                st.metric("최근 분기 영업이익", "데이터 없음")
                        with c2:
                            if not debt_series.empty:
                                latest_debt = debt_series.iloc[-1]
                                delta_debt  = (debt_series.iloc[-1] - debt_series.iloc[-2]) if len(debt_series) >= 2 else None
                                st.metric("최근 분기 부채비율", f"{latest_debt:.1f}%",
                                          delta=f"{delta_debt:+.1f}%" if delta_debt is not None else None,
                                          delta_color="inverse")
                            else:
                                st.metric("최근 분기 부채비율", "데이터 없음")

                        render_financial_chart(name, code, op_series, debt_series)

                        with st.expander("📋 원본 수치 보기"):
                            base_idx = op_series.index.tolist() if not op_series.empty else debt_series.index.tolist()
                            fin_df = pd.DataFrame({
                                '분기':           base_idx,
                                '영업이익(억원)': op_series.values.tolist() if not op_series.empty else [None] * len(base_idx),
                                '부채비율(%)':    debt_series.reindex(base_idx).values.tolist() if not debt_series.empty else [None] * len(base_idx),
                            })
                            st.dataframe(
                                fin_df.style.format({
                                    '영업이익(억원)': lambda v: f"{v:,.0f}" if v is not None else "-",
                                    '부채비율(%)':    lambda v: f"{v:.1f}%" if v is not None else "-",
                                }, na_rep="-"),
                                use_container_width=True, hide_index=True
                            )

                            st.markdown("---")
                            st.markdown("**🏭 업종 정보**")
                            with st.spinner("업종 정보 조회 중..."):
                                sector_info = get_sector_info(code)
                            if sector_info:
                                col_s1, col_s2, col_s3 = st.columns(3)
                                with col_s1:
                                    st.markdown(f"**섹터**  \n{sector_info['sector']}")
                                with col_s2:
                                    st.markdown(f"**업종**  \n{sector_info['industry']}")
                                with col_s3:
                                    emp = sector_info['employees']
                                    st.markdown(f"**임직원 수**  \n{f'{emp:,}명' if emp else '-'}")
                                if sector_info.get('summary'):
                                    summary_text = sector_info['summary'][:300]
                                    if len(sector_info['summary']) > 300:
                                        summary_text += "..."
                                    st.caption(summary_text)
                            else:
                                st.caption("업종 정보를 가져올 수 없습니다.")

                # ── 트레이딩뷰 차트 바로가기 ──
                st.divider()
                st.subheader("📊 트레이딩뷰 차트 바로가기")
                cols_ui = st.columns(5)
                for i, row in enumerate(results):
                    with cols_ui[i % 5]:
                        st.link_button(f"📈 {row['종목명']}", get_chart_url(row['name_raw']), use_container_width=True)

