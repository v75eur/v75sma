import os, io, time, requests, pytz, json, asyncio, websockets
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from datetime import datetime
import pandas as pd

BENIN = pytz.timezone('Africa/Porto-Novo')
CONFIG = json.load(open("config.json"))
SMA_FAST, SMA_SLOW = 3, 25

def log(m): print(f"[{datetime.now().strftime('%H:%M:%S')}] {m}", flush=True)

def post_ntfy(url, msg, img=None, title=None):
    if not url: return
    headers = {"Title": title or "V75 SMA"}
    if img:
        headers["Message"] = msg; headers["Filename"] = "chart.png"
        requests.post(url, data=img, headers=headers, timeout=30)
    else:
        requests.post(url, data=msg.encode("utf-8"), headers=headers, timeout=15)

async def _fetch_deriv(symbol, granularity, count=100):
    uri = 'wss://api.derivws.com/trading/v1/options/ws/public'
    async with websockets.connect(uri, open_timeout=30) as ws:
        await ws.send(json.dumps({'ticks_history': symbol, 'style': 'candles', 'granularity': granularity, 'count': count, 'end': 'latest'}))
        while True:
            data = json.loads(await ws.recv())
            if 'candles' in data: return pd.DataFrame(data['candles'])

def fetch_deriv(symbol, tf):
    gran = {"15m": 900, "30m": 1800, "60m": 3600}.get(tf, 900)
    try:
        df = asyncio.run(_fetch_deriv(symbol, gran))
        if len(df) <= 1: return None
        df = df.rename(columns={"high": "h", "low": "l", "open": "o", "close": "c"})
        return df.iloc[:-1].reset_index(drop=True)
    except Exception as e:
        log(f"Erreur Deriv {symbol}: {e}")
        return None

def tendance(df):
    df["sma_f"] = df["c"].rolling(SMA_FAST).mean()
    df["sma_s"] = df["c"].rolling(SMA_SLOW).mean()
    last = df.iloc[-1]
    if last["sma_f"] > last["sma_s"]: return "HAUSSE"
    if last["sma_f"] < last["sma_s"]: return "BAISSE"
    return "NEUTRE"

def check_sma_croisement(df, sens):
    df["sma_f"] = df["c"].rolling(SMA_FAST).mean()
    df["sma_s"] = df["c"].rolling(SMA_SLOW).mean()
    a, b = df.iloc[-2], df.iloc[-1]
    if sens == "HAUSSE" and a["sma_f"] <= a["sma_s"] and b["sma_f"] > b["sma_s"]: return "ACHAT"
    if sens == "BAISSE" and a["sma_f"] >= a["sma_s"] and b["sma_f"] < b["sma_s"]: return "VENTE"
    return None

def figure(df, tend, sig, tf_label):
    df = df.tail(50).reset_index(drop=True)
    df["sma_f"] = df["c"].rolling(SMA_FAST).mean()
    df["sma_s"] = df["c"].rolling(SMA_SLOW).mean()
    fig, ax = plt.subplots(figsize=(10, 5), dpi=100)
    fig.patch.set_facecolor('#1e1e1e'); ax.set_facecolor('#1e1e1e')
    for i, r in df.iterrows():
        col = '#26a69a' if r['c'] >= r['o'] else '#ef5350'
        ax.plot([i, i], [r['l'], r['h']], color=col, lw=1.2)
        ax.add_patch(Rectangle((i-0.3, min(r['o'], r['c'])), 0.6, abs(r['o']-r['c']), facecolor=col, edgecolor=col))
    ax.plot(df.index, df["sma_f"], color="cyan", lw=1.2, label="SMA 3")
    ax.plot(df.index, df["sma_s"], color="yellow", lw=1.2, label="SMA 25")
    ax.set_title(f"R_75 - {tf_label} | {tend} | {sig or ''}", color="white")
    ax.tick_params(colors='white'); ax.grid(color='#333333', ls='--', alpha=0.5)
    ax.legend(loc="upper left", facecolor='#1e1e1e', labelcolor='white')
    fig.tight_layout()
    buf = io.BytesIO(); fig.savefig(buf, format="png", facecolor=fig.get_facecolor()); plt.close(fig)
    return buf.getvalue()

def main():
    now = datetime.now(BENIN)
    log("DÉMARRAGE SMA")
    
    df_15 = fetch_deriv("R_75", "15m")
    df_30 = fetch_deriv("R_75", "30m")
    df_60 = fetch_deriv("R_75", "60m")
    
    if df_15 is None or df_30 is None or df_60 is None: return
    
    tend_h1 = tendance(df_60)
    tend_m30 = tendance(df_30)
    aligne = (tend_h1 == tend_m30 and tend_h1 in ("HAUSSE", "BAISSE"))
    
    sig = None
    if aligne:
        sig = check_sma_croisement(df_15, tend_h1)
    
    log(f"R_75 analysé. H1:{tend_h1} M30:{tend_m30} Signal: {sig}")
    
    prix = df_15["c"].iloc[-1]
    sma3 = df_15["c"].rolling(SMA_FAST).mean().iloc[-1]
    sma25 = df_15["c"].rolling(SMA_SLOW).mean().iloc[-1]
    
    # Texte du rapport (sans backslash)
    texte = f"📊 **RAPPORT SMA R_75** - {now.strftime('%a %d/%m %H:%M')}\n\n"
    texte += f"🔹 **TENDANCE DE FOND**\n"
    texte += f"• H1 : {tend_h1}\n"
    texte += f"• M30 : {tend_m30}\n"
    if aligne:
        texte += f"• Alignement : ✅ OUI (Les deux sont en {tend_h1})\n\n"
    else:
        texte += f"• Alignement : ❌ NON (H1 et M30 ne sont pas d'accord)\n\n"
    
    texte += f"🔸 **M15 (Entrée)**\n"
    texte += f"• Prix actuel : {prix:.2f}\n"
    texte += f"• SMA 3 : {sma3:.2f}\n"
    texte += f"• SMA 25 : {sma25:.2f}\n\n"
    
    texte += f"🎯 **SIGNAL**\n"
    if sig:
        texte += f"• {sig} CONFIRMÉ ! ✅\n"
        texte += f"• Le croisement à la clôture est validé.\n"
        texte += f"• Conseil : Tu peux envisager une entrée manuelle.\n"
    else:
        if not aligne:
            texte += f"• Aucun signal. ⏳\n"
            texte += f"• Raison : H1 et M30 ne sont pas alignés. Le bot attend que la tendance soit claire.\n"
            texte += f"• Conseil : Patiente, ne trade pas contre la tendance.\n"
        else:
            texte += f"• Aucun signal. ⏳\n"
            texte += f"• Raison : Tendance alignée ({tend_h1}), mais aucun croisement SMA confirmé sur M15.\n"
            texte += f"• Conseil : Attends un croisement haussier (SMA 3 passe au-dessus de SMA 25) pour un achat, ou baissier pour une vente.\n"
            
    texte += f"\n💡 **CONSEIL DU BOT**\n"
    if sig:
        texte += f"• Vérifie les news économiques avant d'entrer.\n"
        texte += f"• Place ton Stop Loss sous le dernier creux (achat) ou au-dessus du dernier sommet (vente).\n"
    else:
        texte += f"• Le marché n'offre pas d'opportunité claire pour le moment.\n"
        texte += f"• Reste patient, le bot te préviendra dès qu'un signal apparaîtra.\n"

    topic = CONFIG["topics"]["principal"]
    if CONFIG["mode_affichage"] == "RAPPORT" or sig:
        for tf, df, tend in [("H1", df_60, tend_h1), ("M30", df_30, tend_m30), ("M15", df_15, tend_h1)]:
            img = figure(df, tend, sig if tf == "M15" else None, tf)
            post_ntfy(topic, f"R_75 - {tf}", img, f"R_75 {tf}")
            time.sleep(1.5)
        
        post_ntfy(topic, texte, None, "Rapport R_75")

if __name__ == "__main__": main()
