# Bot de Valorant para Discord

Bot de Discord con el comando `/valorant` que muestra el **rango actual, el peak y las estadísticas recientes (KDA)** de cualquier jugador de Valorant a partir de su Riot ID.

## Qué hace

- `/valorant riot_id:Jugador#1234 [region]` responde con un embed que incluye:
  - Rango actual y peak (mejor rango histórico).
  - Resumen de las últimas partidas competitivas (KDA y resultado).
  - Enlace directo al perfil en tracker.gg.
- Cooldown de 10 segundos por usuario para no saturar la API.
- Opción de restringir el comando a un único canal.
- Incluye un mini servidor web (`aiohttp`) para que servicios de hosting gratuitos (por ejemplo Render) puedan hacer *health checks* y mantener el bot activo.

> **Fuente de datos:** [HenrikDev API](https://docs.henrikdev.xyz/) (no oficial, gratuita con API key). No se hace scraping de tracker.gg, solo se enlaza al perfil.

## Stack

- Python 3.10+
- [`discord.py`](https://discordpy.readthedocs.io/) 2.4+ (slash commands)
- `aiohttp` (peticiones HTTP asíncronas y servidor de health check)
- `python-dotenv`

## Instalación

```bash
git clone https://github.com/tomasjdev/Bot-Valorant.git
cd Bot-Valorant
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env           # y completa las variables
python bot.py
```

## Variables de entorno

| Variable | Descripción |
|---|---|
| `DISCORD_TOKEN` | Token del bot (Discord Developer Portal). |
| `HENRIK_API_KEY` | API key de HenrikDev (`HDEV-...`). |
| `DEFAULT_REGION` | Región por defecto: `na` (LATAM/Norteamérica), `eu`, `ap`, `kr`. |
| `ALLOWED_CHANNEL_ID` | *(Opcional)* ID del canal donde se permite el comando. Vacío = todos. |
| `MATCH_SAMPLE` | Cantidad de partidas recientes que se analizan (por defecto `10`). |
| `PORT` | *(Opcional)* Puerto del servidor de health check (por defecto `8080`). |

> Nunca subas tu archivo `.env` al repositorio. Ya está en `.gitignore`.

## Despliegue

Pensado para correr en un servicio gratuito tipo Render como *Web Service*: comando de inicio `python bot.py`, con las variables de entorno configuradas en el panel del servicio.

## Estructura

```text
bot.py             # Bot, comando /valorant y llamadas a la API
requirements.txt   # Dependencias
.env.example       # Plantilla de variables de entorno
```
