"""Bot de Discord: /valorant Nombre#TAG -> rango actual, peak, KDA y más.

Fuente de datos: HenrikDev API (no oficial, gratis con API key).
Nota: no se hace scraping de tracker.gg (Cloudflare + términos de uso).
"""
import asyncio
import logging
import os
import time
from urllib.parse import quote

import aiohttp
import discord
from aiohttp import web
from discord import app_commands
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
HENRIK_KEY = os.environ["HENRIK_API_KEY"]
DEFAULT_REGION = os.getenv("DEFAULT_REGION", "na")  # LATAM/Chile cae en "na"
# Opcional: restringe el comando a un canal (ID). Vacío = cualquier canal.
ALLOWED_CHANNEL_ID = int(os.getenv("ALLOWED_CHANNEL_ID", "0") or 0)
MATCH_SAMPLE = int(os.getenv("MATCH_SAMPLE", "10"))  # partidas competitivas a promediar
CACHE_TTL = 300  # segundos; protege el límite de 30 req/min de la key básica

API = "https://api.henrikdev.xyz/valorant"
REGIONS = ["na", "eu", "ap", "kr"]

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("valorant-bot")


class ProfileUnavailable(Exception):
    """Cuenta inexistente o sin datos visibles."""


class RateLimited(Exception):
    pass


# ---------- API ----------
_cache: dict[str, tuple[float, dict]] = {}


async def henrik_get(session: aiohttp.ClientSession, path: str, params=None):
    async with session.get(
        f"{API}{path}",
        params=params,
        headers={"Authorization": HENRIK_KEY},
        timeout=aiohttp.ClientTimeout(total=15),
    ) as r:
        if r.status == 404:
            raise ProfileUnavailable
        if r.status == 429:
            raise RateLimited
        if r.status >= 400:
            raise RuntimeError(f"Henrik API {r.status}: {await r.text()}")
        return await r.json()


def parse_riot_id(raw: str) -> tuple[str, str]:
    name, sep, tag = raw.strip().rpartition("#")
    if not sep or not name.strip() or not tag.strip():
        raise ValueError
    return name.strip(), tag.strip()


async def fetch_profile(session, region: str, name: str, tag: str) -> dict:
    key = f"{region}:{name.lower()}#{tag.lower()}"
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_TTL:
        return hit[1]

    n, t = quote(name, safe=""), quote(tag, safe="")
    mmr_task = henrik_get(session, f"/v3/mmr/{region}/pc/{n}/{t}")
    mt_task = henrik_get(
        session,
        f"/v4/matches/{region}/pc/{n}/{t}",
        {"mode": "competitive", "size": MATCH_SAMPLE},
    )
    mmr_res, mt_res = await asyncio.gather(mmr_task, mt_task, return_exceptions=True)

    # Sin MMR no hay nada que mostrar: propaga el error real.
    if isinstance(mmr_res, Exception):
        raise mmr_res
    # Las partidas son un extra: si fallan, mostramos solo el rango.
    matches = [] if isinstance(mt_res, Exception) else mt_res.get("data", [])

    data = {"mmr": mmr_res["data"], "stats": compute_stats(mmr_res["data"], matches)}
    _cache[key] = (time.time(), data)
    return data


def compute_stats(mmr: dict, matches: list[dict]) -> dict | None:
    puuid = mmr["account"]["puuid"]
    k = d = a = hs = shots = score = rounds = wins = games = 0
    agents: dict[str, int] = {}
    for m in matches:
        me = next((p for p in m.get("players", []) if p["puuid"] == puuid), None)
        if not me:
            continue
        s = me["stats"]
        k, d, a = k + s["kills"], d + s["deaths"], a + s["assists"]
        hs += s["headshots"]
        shots += s["headshots"] + s["bodyshots"] + s["legshots"]
        score += s["score"]
        teams = m.get("teams", [])
        rounds += sum(t["rounds"]["won"] + t["rounds"]["lost"] for t in teams[:1])
        mine = next((t for t in teams if t["team_id"] == me["team_id"]), None)
        wins += 1 if mine and mine["won"] else 0
        games += 1
        ag = me["agent"]["name"]
        agents[ag] = agents.get(ag, 0) + 1
    if not games:
        return None
    return {
        "games": games,
        "wins": wins,
        "kd": k / max(d, 1),
        "kda": (k + a) / max(d, 1),
        "acs": score / max(rounds, 1),
        "hs": hs / max(shots, 1) * 100,
        "top_agents": sorted(agents, key=agents.get, reverse=True)[:3],
    }


# ---------- Discord ----------
def build_embed(mmr: dict, stats: dict | None, region: str) -> discord.Embed:
    acc, cur, peak = mmr["account"], mmr["current"], mmr.get("peak")
    cur_txt = f"**{cur['tier']['name']}** · {cur['rr']} RR"
    if cur.get("leaderboard_placement"):
        cur_txt += f" · #{cur['leaderboard_placement']['rank']} leaderboard"
    peak_txt = (
        f"**{peak['tier']['name']}** ({peak['season']['short'].upper()})"
        if peak
        else "Sin datos"
    )
    e = discord.Embed(
        title=f"{acc['name']}#{acc['tag']}",
        url=f"https://tracker.gg/valorant/profile/riot/{quote(acc['name'])}%23{quote(acc['tag'])}/overview",
        color=0xFF4655,
    )
    e.add_field(name="Rango actual", value=cur_txt)
    e.add_field(name="Peak", value=peak_txt)
    if stats:
        wr = stats["wins"] / stats["games"] * 100
        e.add_field(
            name=f"Últimas {stats['games']} competitivas",
            value=(
                f"K/D **{stats['kd']:.2f}** · KDA **{stats['kda']:.2f}**\n"
                f"ACS **{stats['acs']:.0f}** · HS **{stats['hs']:.0f}%**\n"
                f"Winrate **{wr:.0f}%** ({stats['wins']}/{stats['games']})\n"
                f"Agentes: {', '.join(stats['top_agents'])}"
            ),
            inline=False,
        )
    else:
        e.add_field(name="Partidas recientes", value="Sin partidas competitivas visibles.", inline=False)
    e.set_footer(text=f"Región: {region.upper()} · Datos: HenrikDev API · Enlace: tracker.gg")
    return e


class Bot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())  # slash commands: sin Message Content
        self.tree = app_commands.CommandTree(self)
        self.http_session: aiohttp.ClientSession | None = None

    async def setup_hook(self):
        self.http_session = aiohttp.ClientSession()
        await self.tree.sync()
        # Mini servidor HTTP para que Render (web service) detecte el puerto.
        app = web.Application()
        app.router.add_get("/", lambda _: web.Response(text="ok"))
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, "0.0.0.0", int(os.getenv("PORT", "8080"))).start()


bot = Bot()


@bot.tree.command(name="valorant", description="Rango, peak y stats de un jugador de Valorant")
@app_commands.describe(riot_id="Riot ID, ej: Jugador#1234", region="Región (por defecto LATAM = na)")
@app_commands.choices(region=[app_commands.Choice(name=r.upper(), value=r) for r in REGIONS])
@app_commands.checks.cooldown(1, 10.0, key=lambda i: i.user.id)
async def valorant(i: discord.Interaction, riot_id: str, region: app_commands.Choice[str] | None = None):
    if ALLOWED_CHANNEL_ID and i.channel_id != ALLOWED_CHANNEL_ID:
        return await i.response.send_message(
            f"Usa este comando en <#{ALLOWED_CHANNEL_ID}>.", ephemeral=True
        )
    try:
        name, tag = parse_riot_id(riot_id)
    except ValueError:
        return await i.response.send_message("Formato inválido. Usa `Nombre#TAG`.", ephemeral=True)

    await i.response.defer()
    reg = region.value if region else DEFAULT_REGION
    try:
        data = await fetch_profile(bot.http_session, reg, name, tag)
    except ProfileUnavailable:
        return await i.followup.send(
            f"❌ No es posible ver el perfil de **{name}#{tag}** en {reg.upper()}: "
            "la cuenta no existe, está en otra región o no tiene datos visibles."
        )
    except RateLimited:
        return await i.followup.send("⏳ Demasiadas consultas, intenta de nuevo en un minuto.")
    except Exception:
        log.exception("Error consultando la API")
        return await i.followup.send("⚠️ Error consultando la API. Intenta más tarde.")

    mmr = data["mmr"]
    if not mmr.get("peak") and mmr["current"]["tier"]["id"] == 0 and not data["stats"]:
        return await i.followup.send(
            f"❌ **{name}#{tag}** existe pero no tiene datos competitivos visibles."
        )
    await i.followup.send(embed=build_embed(mmr, data["stats"], reg))


@valorant.error
async def on_error(i: discord.Interaction, err: app_commands.AppCommandError):
    if isinstance(err, app_commands.CommandOnCooldown):
        await i.response.send_message(f"Espera {err.retry_after:.0f}s.", ephemeral=True)
    else:
        log.exception("Error no controlado", exc_info=err)


if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
