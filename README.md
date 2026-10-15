# Backend de CapturaGPT

Este proyecto se despliega en Render. Las claves de OpenAI y Supabase permanecen en las variables privadas del servicio. El cliente solo conoce la URL pública del backend.

## Estado del proyecto

- Servicio: `https://capturagpt-backend.onrender.com`
- Base de datos: Supabase, proyecto `vrdjmhjceunebuhvfuxg`
- Migraciones de cuentas: `auth_schema.sql` y `bind_account_device.sql`
- Cuenta de prueba: `capturagpt_admin`, con 50 créditos iniciales

## Variables privadas

Render ya tiene `OPENAI_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `OPENAI_MODEL` y `AUTH_TOKEN_SECRET`. El archivo `.env` local es privado y está excluido de Git. Si despliegas otro servidor, configura esas variables en el nuevo servicio.

## API

`POST /api/v1/auth/login` recibe `username`, `password` y `hardware_id` en un formulario. Verifica la contraseña en el backend, vincula el primer equipo de forma atómica en Supabase y devuelve un token de sesión y `credits_left`.

`POST /api/v1/analyze` recibe un JPEG o PNG en `multipart/form-data` con el encabezado `Authorization: Bearer <token>`. Valida la sesión, descuenta un crédito mediante la RPC `consume_account_credit` y llama a OpenAI. Devuelve `result` y `credits_left`.

El antiguo script `generar_clave.py` y la tabla `licenses` se conservan para compatibilidad, pero el cliente actual utiliza usuario y contraseña.

## Ejecutar localmente

```powershell
Set-Location 'C:\Users\jzamb\Documents\capturas de chat\backend_servidor'
.\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
.\.venv\Scripts\uvicorn.exe server:app --host 127.0.0.1 --port 8787
```

El cliente actual apunta a Render. Para probar contra el servidor local, cambia `API_URL` en el `config.json` local a `http://127.0.0.1:8787`.

## Crear otra cuenta por comandos

```powershell
.\.venv\Scripts\python.exe .\crear_cuenta.py nombre_usuario contraseña_temporal --credits 50
```

No guardes contraseñas en scripts ni en archivos del cliente. El script almacena únicamente un hash `scrypt` en Supabase.
