import streamlit as st
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import ta
import pandas as pd

# --- ページ設定 ---
st.set_page_config(page_title="株式売買判断ツール", layout="wide")
st.title("📈 株式売買判断ツール")
st.caption("日本の個別株のテクニカル指標をチェックして、買い時かどうかを判断します")

# --- スマホ向けスタイル調整 ---
st.markdown("""
<style>
    /* 全体の余白を詰める */
    .block-container {
        padding-top: 1rem;
        padding-bottom: 0rem;
    }
    /* 見出しサイズを調整 */
    h1 { font-size: 1.5rem !important; }
    h2 { font-size: 1.2rem !important; }
    h3 { font-size: 1.0rem !important; }
    /* メトリクスのサイズ調整 */
    [data-testid="stMetricValue"] {
        font-size: 1.2rem !important;
    }
    /* サイドバーの幅を調整 */
    @media (max-width: 768px) {
        h1 { font-size: 1.3rem !important; }
        h2 { font-size: 1.1rem !important; }
    }
</style>
""", unsafe_allow_html=True)


# --- 東証銘柄リストの取得（キャッシュで高速化） ---
@st.cache_data(ttl=86400)
def load_stock_list():
    url = "https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.xls"
    df = pd.read_excel(url)
    # 必要な列だけ取得（銘柄コード、銘柄名）
    # 列名はファイルの構造に合わせる
    df = df[["コード", "銘柄名"]].dropna()
    df["コード"] = df["コード"].astype(str).str.strip()
    df["銘柄名"] = df["銘柄名"].astype(str).str.strip()
    return df

try:
    stock_list_df = load_stock_list()
    stock_list_loaded = True
except Exception as e:
    stock_list_loaded = False
    st.sidebar.warning("銘柄リストの取得に失敗しました。証券コードで入力してください。")

# --- 入力エリア ---
st.sidebar.header("🔍 銘柄を入力")
input_method = st.sidebar.radio("入力方法", ["会社名で検索", "証券コードで入力"])

ticker_code = None
company_name = None

# 半角→全角変換用
def to_fullwidth(text):
    result = ""
    for char in text:
        code = ord(char)
        if 0x21 <= code <= 0x7E:
            result += chr(code + 0xFEE0)
        elif code == 0x20:
            result += "\u3000"
        else:
            result += char
    return result

if input_method == "会社名で検索":
    search_text = st.sidebar.text_input("会社名を入力（例：ソフトバンク、東急、SBI）")
    if search_text and stock_list_loaded:
        # 半角・全角両方で検索
        search_full = to_fullwidth(search_text)
        matches = stock_list_df[
            stock_list_df["銘柄名"].str.contains(search_text, case=False, na=False) |
            stock_list_df["銘柄名"].str.contains(search_full, case=False, na=False)
        ]
        if not matches.empty:
            options = {f"{row['銘柄名']}（{row['コード']}）": row for _, row in matches.head(20).iterrows()}
            selected = st.sidebar.selectbox("候補を選択", list(options.keys()))
            ticker_code = options[selected]["コード"]
            company_name = options[selected]["銘柄名"]
        else:
            st.sidebar.warning("見つかりません。別のキーワードか証券コードで入力してください。")
    elif search_text and not stock_list_loaded:
        st.sidebar.warning("銘柄リストが読み込めていません。証券コードで入力してください。")
else:
    raw_code = st.sidebar.text_input("証券コード（例：7203）")
    if raw_code:
        # 全角数字→半角数字に変換
        normalized = raw_code.translate(str.maketrans("０１２３４５６７８９", "0123456789")).strip()
        # バリデーション：半角数字4桁かチェック
        if not normalized.isdigit() or len(normalized) != 4:
            st.sidebar.error("証券コードは半角数字4桁で入力してください（例：7203）")
        else:
            ticker_code = normalized
            if stock_list_loaded:
                match = stock_list_df[stock_list_df["コード"] == ticker_code]
                if not match.empty:
                    company_name = match.iloc[0]["銘柄名"]
                else:
                    company_name = f"銘柄 {ticker_code}"
            else:
                company_name = f"銘柄 {ticker_code}"

# --- メイン処理 ---
if ticker_code:
    symbol = f"{ticker_code}.T"
    
    with st.spinner("データを取得中..."):
        df = yf.download(symbol, period="6mo", interval="1d")
    
    if df.empty:
        st.error("データを取得できませんでした。証券コードを確認してください。")
    else:
        # MultiIndex対応
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        
        # --- テクニカル指標の計算 ---
        # 移動平均線
        df["MA5"] = ta.trend.sma_indicator(df["Close"], window=5)
        df["MA25"] = ta.trend.sma_indicator(df["Close"], window=25)
        df["MA75"] = ta.trend.sma_indicator(df["Close"], window=75)
        
        # MACD
        macd = ta.trend.MACD(df["Close"])
        df["MACD"] = macd.macd()
        df["MACD_signal"] = macd.macd_signal()
        df["MACD_hist"] = macd.macd_diff()
        
        # RSI
        df["RSI"] = ta.momentum.rsi(df["Close"], window=14)
        
        # ATR（損切り目安用）
        df["ATR"] = ta.volatility.average_true_range(
            df["High"], df["Low"], df["Close"], window=14
        )
        
        # 最新データ
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        current_price = latest["Close"]
        
        # --- 判定ロジック ---
        signals = []
        reasons = []
        
        # 1. 移動平均線の判定
        if latest["MA5"] > latest["MA25"]:
            if prev["MA5"] <= prev["MA25"]:
                signals.append(2)
                reasons.append("🟢 ゴールデンクロス発生！（5日線が25日線を上抜け）")
            else:
                signals.append(1)
                reasons.append("🟢 短期トレンドは上向き（5日線 > 25日線）")
        else:
            if prev["MA5"] >= prev["MA25"]:
                signals.append(-2)
                reasons.append("🔴 デッドクロス発生！（5日線が25日線を下抜け）")
            else:
                signals.append(-1)
                reasons.append("🔴 短期トレンドは下向き（5日線 < 25日線）")
        
        if current_price > latest["MA75"]:
            signals.append(1)
            reasons.append("🟢 株価は75日線より上（中期トレンドは上向き）")
        else:
            signals.append(-1)
            reasons.append("🔴 株価は75日線より下（中期トレンドは下向き）")
        
        # 2. MACDの判定
        if latest["MACD"] > latest["MACD_signal"]:
            if prev["MACD"] <= prev["MACD_signal"]:
                signals.append(2)
                reasons.append("🟢 MACDがシグナルを上抜け（買いシグナル）")
            else:
                signals.append(1)
                reasons.append("🟢 MACDはシグナルより上（上昇傾向）")
        else:
            if prev["MACD"] >= prev["MACD_signal"]:
                signals.append(-2)
                reasons.append("🔴 MACDがシグナルを下抜け（売りシグナル）")
            else:
                signals.append(-1)
                reasons.append("🔴 MACDはシグナルより下（下降傾向）")
        
        # 3. RSIの判定
        rsi_value = latest["RSI"]
        if rsi_value < 30:
            signals.append(2)
            reasons.append(f"🟢 RSI = {rsi_value:.1f}（売られすぎ → 反発の可能性）")
        elif rsi_value < 50:
            signals.append(1)
            reasons.append(f"🟡 RSI = {rsi_value:.1f}（やや売られ気味）")
        elif rsi_value < 70:
            signals.append(0)
            reasons.append(f"🟡 RSI = {rsi_value:.1f}（普通の水準）")
        else:
            signals.append(-1)
            reasons.append(f"🔴 RSI = {rsi_value:.1f}（買われすぎ → 過熱注意）")
        
        # 4. 出来高の判定
        vol_avg = df["Volume"].tail(20).mean()
        vol_today = latest["Volume"]
        vol_ratio = vol_today / vol_avg if vol_avg > 0 else 1
        
        if vol_ratio > 1.5:
            if sum(signals) > 0:
                signals.append(1)
                reasons.append(f"🟢 出来高が平均の{vol_ratio:.1f}倍（上昇に勢いあり）")
            else:
                reasons.append(f"🟡 出来高が平均の{vol_ratio:.1f}倍（売りの勢いにも注意）")
        else:
            reasons.append(f"⚪ 出来高は平均的（{vol_ratio:.1f}倍）")
        
        # 総合判定
        total_score = sum(signals)
        
        if total_score >= 4:
            judgment = "🟢 強い買いシグナル"
            judgment_color = "green"
            judgment_msg = "複数の指標が買いを示しています。エントリーのチャンスです！"
        elif total_score >= 2:
            judgment = "🟢 買いシグナル"
            judgment_color = "green"
            judgment_msg = "買いの条件が揃いつつあります。タイミングを見て検討しましょう。"
        elif total_score >= 0:
            judgment = "🟡 様子見"
            judgment_color = "orange"
            judgment_msg = "まだシグナルが明確ではありません。もう少し待ちましょう。"
        else:
            judgment = "🔴 今は買い時ではない"
            judgment_color = "red"
            judgment_msg = "下降トレンドの可能性があります。見送りが無難です。"
        
        # 損切り目安
        atr_value = latest["ATR"]
        stop_loss = current_price - (atr_value * 2)
        
        # --- 表示 ---
        st.header(f"{company_name}（{ticker_code}）")
        st.metric("現在株価", f"¥{current_price:,.0f}")
        
        # 判定結果
        st.subheader("💡 判定結果")
        st.markdown(
            f"<h2 style='color:{judgment_color};'>{judgment}</h2>",
            unsafe_allow_html=True,
        )
        st.write(judgment_msg)
        
        # 損切り目安
        st.info(
            f"📉 損切り目安：¥{stop_loss:,.0f}（現在値からATRの2倍 = ¥{atr_value * 2:,.0f} 下）"
        )
        
                # 判定基準の説明（折りたたみ）
        with st.expander("📖 判定基準を見る"):
            st.markdown("""
**【スコアによる総合判定】**
- **強い買いシグナル**：合計スコア 4以上
- **買いシグナル**：合計スコア 2〜3
- **様子見**：合計スコア 0〜1
- **今は買い時ではない**：合計スコア マイナス

---

**【移動平均線】（最大 +3 / 最小 -3）**
- ゴールデンクロス発生（5日線が25日線を上抜け）：+2
- 短期トレンド上向き（5日線 > 25日線）：+1
- デッドクロス発生（5日線が25日線を下抜け）：-2
- 短期トレンド下向き（5日線 < 25日線）：-1
- 株価が75日線より上：+1
- 株価が75日線より下：-1

---

**【MACD】（最大 +2 / 最小 -2）**
- MACDがシグナルを上抜け：+2
- MACDがシグナルより上：+1
- MACDがシグナルを下抜け：-2
- MACDがシグナルより下：-1

---

**【RSI】（最大 +2 / 最小 -1）**
- RSI 30未満（売られすぎ → 反発期待）：+2
- RSI 30〜50（やや売られ気味）：+1
- RSI 50〜70（普通）：0
- RSI 70以上（買われすぎ → 過熱注意）：-1

---

**【出来高】（最大 +1 / 最小 0）**
- 出来高が20日平均の1.5倍以上 かつ 他の指標が買い寄り：+1
- それ以外：スコアに影響なし

---

**【損切り目安】**
- ATR（14日間の平均的な値動き幅）の2倍を現在値から引いた価格
- 銘柄の値動きの大きさに応じて自動調整されます
            """)


        # 判定根拠
        st.subheader("📊 判定の根拠")
        for reason in reasons:
            st.write(reason)
        
        # --- チャート ---
        st.subheader("📈 チャート")
        
        fig = make_subplots(
            rows=4, cols=1, shared_xaxes=True,
            vertical_spacing=0.05,
            row_heights=[0.4, 0.2, 0.2, 0.2],
            subplot_titles=("株価チャート", "MACD", "RSI", "出来高"),
        )
        
        # ローソク足
        fig.add_trace(
            go.Candlestick(
                x=df.index, open=df["Open"], high=df["High"],
                low=df["Low"], close=df["Close"], name="株価",
            ),
            row=1, col=1,
        )
        # 移動平均線
        for ma, color in [("MA5", "blue"), ("MA25", "orange"), ("MA75", "red")]:
            fig.add_trace(
                go.Scatter(x=df.index, y=df[ma], name=ma, line=dict(color=color, width=1)),
                row=1, col=1,
            )
        # 損切りライン
        fig.add_hline(
            y=stop_loss, line_dash="dash", line_color="red",
            annotation_text=f"損切り目安 ¥{stop_loss:,.0f}",
            row=1, col=1,
        )
        
        # MACD
        fig.add_trace(
            go.Scatter(x=df.index, y=df["MACD"], name="MACD", line=dict(color="blue")),
            row=2, col=1,
        )
        fig.add_trace(
            go.Scatter(x=df.index, y=df["MACD_signal"], name="Signal", line=dict(color="orange")),
            row=2, col=1,
        )
        fig.add_trace(
            go.Bar(x=df.index, y=df["MACD_hist"], name="Histogram"),
            row=2, col=1,
        )
        
        # RSI
        fig.add_trace(
            go.Scatter(x=df.index, y=df["RSI"], name="RSI", line=dict(color="purple")),
            row=3, col=1,
        )
        fig.add_hline(y=70, line_dash="dash", line_color="red", row=3, col=1)
        fig.add_hline(y=30, line_dash="dash", line_color="green", row=3, col=1)
        
        # 出来高
        fig.add_trace(
            go.Bar(x=df.index, y=df["Volume"], name="出来高"),
            row=4, col=1,
        )
        
        fig.update_layout(
            height=600,
            xaxis_rangeslider_visible=False,
            showlegend=True,
            margin=dict(l=10, r=10, t=30, b=10),
        )
        
        st.plotly_chart(fig, use_container_width=True)
else:
    st.info("👈 左のメニューから銘柄を入力してください")
