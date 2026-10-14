# Backend servidor independiente

Este proyecto se ejecuta por separado. `server.py` no importa archivos de CapturaGPT. Mantén esta carpeta y su `.env` únicamente en tu servidor; los compradores reciben solo el cliente.

## Requisito de Supabase

El proyecto Supabase usado en la sesión anterior (`https://vrdjmhjceunebuhvfuxg.supabase.co`) ya tiene la tabla `licenses` y la función RPC `consume_credit`. Si usas otro proyecto, ejecuta [sql/001_licenses.sql](sql/001_licenses.sql) una vez en su SQL Editor antes de generar licencias. La función descuenta un crédito y vincula la primera máquina de forma atómica.

## Instalación exacta en PowerShell

```powershell
Set-Location 'C:\Users\jzamb\Documents\capturas de chat\backend_servidor'
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
Copy-Item .\.env.example .\.env
notepad .\.env
```

En el Bloc de notas, completa y guarda estas tres líneas en `.env`:

```dotenv
OPENAI_API_KEY=tu_clave_privada_de_OpenAI
SUPABASE_URL=https://vrdjmhjceunebuhvfuxg.supabase.co
SUPABASE_SERVICE_ROLE_KEY=tu_service_role_key_privada
```

Obtén `SUPABASE_SERVICE_ROLE_KEY` en el panel del proyecto Supabase, sección **Project Settings → API Keys**. Usa la clave `service_role` del proyecto indicado; no uses la clave pública `anon`. No pegues estas claves en el cliente ni en un repositorio. `OPENAI_MODEL` es opcional: el servidor usa `gpt-5.6` por defecto. En esta instalación se configuró `gpt-4o` porque la clave disponible no tiene acceso a `gpt-5.6`.

Genera una licencia de prueba real, con 50 créditos:

```powershell
.\.venv\Scripts\python.exe .\generar_clave.py
```

El script imprime la clave solo después de que Supabase confirma la inserción. Copia ese valor en el botón **Ingresar clave de licencia** del cliente. Cada ejecución crea otra licencia.

Para verificar el proyecto sin usar claves ni créditos reales:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Inicia el servidor y deja esa terminal abierta:

```powershell
.\.venv\Scripts\python.exe -m uvicorn server:app --host 127.0.0.1 --port 8000
```

En otra terminal, comprueba que responde:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

Debe mostrar `status: ok`. Para que el cliente en otra máquina pueda conectarse, publica este servicio por HTTPS y configura la URL base en el cliente. Una prueba local con Cloudflare Tunnel usa `cloudflared tunnel --url http://localhost:8000`; esa URL temporal cambia al reiniciarlo. Para uso estable, configura un túnel con dominio propio o un hosting con HTTPS.

Para Render, publica **solo esta carpeta** como repositorio independiente y crea un Blueprint desde [render.yaml](render.yaml). Render solicitará los tres secretos marcados con `sync: false`; introdúcelos en el panel de Render, nunca en Git. Cuando el despliegue termine, sustituye `API_URL` en `capturagpt_comercial/client/config.json` por la URL HTTPS `onrender.com` del servicio. El despliegue en Render requiere conectar una cuenta y un repositorio de código; el túnel local anterior funciona mientras tanto.

## API y cobro

`POST /api/v1/analyze` recibe `multipart/form-data` con `license_key`, `hardware_id` (SHA-256 hexadecimal de 64 caracteres) e `image` (JPEG/PNG). Valida la imagen, consume un crédito por RPC y solo entonces llama a OpenAI. Devuelve `{"result":"A y C","credits_left":49}`. Responde 402 sin créditos y 403 por licencia inválida o equipo distinto; en ambos casos no llama a OpenAI.

Si OpenAI falla después del débito, devuelve 502 con el saldo descontado. Revisa esos casos y repón créditos manualmente cuando corresponda. El servidor no hace reintentos automáticos a OpenAI.
