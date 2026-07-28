# Sincronización automática del token de Schwab (Mac + PC + Render)

El token de Schwab se vence cada ~7 días y hay que re-loguearse a mano (no se puede
automatizar ese login). Para que **nunca** tengas que copiar el token de una máquina a
otra, Render es el **hub central**: la PC lo sube, todas las demás máquinas lo bajan.

## Lo ÚNICO que tienes que hacer una vez

1. **Crear una API Key de Render**
   - Render → foto de perfil (arriba a la derecha) → **Account Settings** → **API Keys**
     → **Create API Key**. Cópiala (empieza con `rnd_...`).
2. **Copiar el Service ID**
   - Abre el servicio `drift-sentiment-web` en el dashboard de Render. En la URL verás
     algo como `.../web/srv-abc123def456`. Ese `srv-...` es el Service ID.
3. **Pegarlos en el `.env`**
   - **En la PC (obligatorio)** — es la que renueva el token y lo empuja a la nube:
     ```
     RENDER_API_KEY=rnd_xxxxxxxxxxxxxxxx
     RENDER_SERVICE_ID=srv-xxxxxxxxxxxx
     ```
   - **En el Mac (opcional pero recomendado)** — para que el Mac se auto-cure solo,
     pega esas MISMAS dos líneas en su `.env`.

Eso es todo. El `.env` está en `.gitignore`, así que estas claves nunca se suben a
GitHub.

## Cómo funciona el ciclo completo

1. **La PC es la maestra.** Cuando el token se vence, te llega un aviso por WhatsApp.
   Corres el re-login en la PC (`schwab-login.cmd` → login → Approve). Al terminar,
   `scripts/schwab_auth.py` **empuja** el token fresco a Render solo
   (`scripts/render_push_token.py`: actualiza la variable `SCHWAB_REFRESH_TOKEN` y
   dispara un redeploy). La nube queda al día sin que copies nada.

2. **El Mac (y la nube al arrancar) se curan solos.** `scripts/schwab_sync.py`:
   - Si el token local todavía sirve → no hace nada (ni siquiera llama a Render).
   - Si el token local está vencido → **baja** el fresco de Render
     (`scripts/render_pull_token.py`) y sigue funcionando **sin re-login**.
   - Solo si Render tampoco puede ayudar concluye que hace falta re-login en la PC.

3. **El aviso diario ya no molesta de gancho.** `scripts/schwab_reauth_check.py`
   intenta primero bajar el token de Render; solo te avisa si de verdad hace falta
   re-loguear.

## Regla de oro

**Re-loguéate SIEMPRE en la PC, nunca en el Mac.** Schwab da un solo refresh token por
app; si te logueas en dos máquinas, invalidas el de la otra. El Mac se sincroniza
bajando de Render, nunca re-autenticando.

## Comandos útiles (a mano, opcional)

```bash
# Bajar el token más fresco de Render al Mac (sin re-login):
.venv/bin/python scripts/render_pull_token.py

# Ver/curar el estado del token local (baja de Render si está vencido):
.venv/bin/python scripts/schwab_sync.py

# Subir el token local a Render (normalmente lo hace schwab_auth.py solo):
.venv/bin/python scripts/render_push_token.py
```
