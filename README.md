# Tablero de oportunidades — Banquetería Gran Concepción

Monitor automático de licitaciones de Mercado Público filtradas a los rubros de
la banquetería (OrgCode **891391**), con detección de zona (Gran Concepción /
Biobío / Nacional) y palabras clave. Se actualiza solo cada 12 h.

## Piezas

- **`motor.py`** — lee el feed RSS, filtra y escribe `data.json`. Sin dependencias.
- **`index.html`** — el tablero (GitHub Pages) que muestra `data.json`.
- **`data.json`** — datos actuales (lo regenera el motor).
- **`.github/workflows/actualizar.yml`** — corre el motor cada 12 h.

## Dejarlo andando (una sola vez, ~10 min)

1. Crea una cuenta gratis en https://github.com y un repositorio **público** nuevo
   (ej: `oportunidades-banqueteria`).
2. Sube estos 4 archivos (botón **Add file → Upload files**), respetando la carpeta
   `.github/workflows/`.
3. Activa GitHub Pages: **Settings → Pages → Source: Deploy from a branch →
   Branch: `main` / carpeta `/root` → Save**. En 1-2 minutos tu tablero queda en
   `https://TU-USUARIO.github.io/oportunidades-banqueteria/`.
4. Deja que el motor corra solo (cada 12 h) o córrelo a mano en **Actions →
   Actualizar oportunidades → Run workflow**.

Con eso ya está andando: el tablero muestra las oportunidades y el motor las
refresca dos veces al día.

## Opcional: fechas de cierre (API)

El RSS no trae la fecha de cierre. Para ver la cuenta regresiva de cada licitación:

1. Pide un **ticket** gratis en https://api.mercadopublico.cl (llega por correo).
2. En el repo: **Settings → Secrets and variables → Actions → New repository secret**
   - Nombre: `MP_TICKET`
   - Valor: tu ticket
3. La próxima ejecución del motor enriquecerá cada licitación con su fecha de cierre
   y monto, y el tablero mostrará la cuenta regresiva.

## Ajustes rápidos

- **Cambiar el OrgCode**: edita `MP_ORGCODE` en `actualizar.yml`.
- **Cambiar comunas/palabras clave**: edita las listas `GRAN_CONCEPCION`, `BIOBIO`
  y `KEYWORDS` al inicio de `motor.py`.

## Notas honestas

- Cubre **licitaciones** (lo que entrega el RSS). Compra Ágil no viene en el feed;
  para eso se usa la alerta por correo del portal.
- La detección de zona es por texto del comprador: muy buena, pero puede fallar en
  casos raros. Ante la duda, usa el filtro "Todo Chile".
- Para postular necesitas estar **Hábil** (acreditación de ChileProveedores al día).
