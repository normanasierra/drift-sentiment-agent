Genera un brief PRE-MERCADO diario de EE. UU., en ESPAÑOL. Herramienta
educativa — **no es asesoría financiera**. Nunca digas "compra" o "vende";
solo datos, niveles y contexto para que el lector decida.

## Contexto

Este run ocurre una mañana de día hábil bursátil (~9:00 hora local, UTC-4).
Enfócate en la SESIÓN COMPLETADA más reciente y en el pre-mercado / overnight
de hoy. Usa **WebSearch / WebFetch**; nunca inventes cifras (marca lo que no
encuentres como "n/d"). Sé eficiente con las búsquedas (agrupa, prioriza).

## Pasos de investigación

1. **Mercado general**: SPY y QQQ (nivel, cambio %, niveles clave), VIX (nivel
   y dirección), Tesoro a 10 años (nivel y dirección). Forma una lectura:
   **Risk-On / Risk-Off / Mixto** con una frase de justificación.

2. **Noticias**: revisa **Yahoo Finance** (finance.yahoo.com) y **CNBC**
   (cnbc.com) como fuentes principales. Saca los **3-5 titulares macro** que
   muevan la renta variable de EE. UU. hoy, cada uno con una frase de "por qué
   importa". (Barron's suele estar tras muro de pago: usa solo titulares
   públicos si aparecen.)

3. **Trump**: busca lo más reciente y relevante para el MERCADO que haya dicho
   o hecho Trump (declaraciones, aranceles, Fed, política económica, órdenes
   ejecutivas). Resume en 2-4 viñetas con enfoque en impacto de mercado. Si no
   hay nada relevante hoy, dilo en una línea.

4. **Portafolio del lector** (educativo, NO recomendaciones): estos son sus
   tickers. Para cada uno consigue el cambio % del día (o pre-mercado) y anota
   solo si hay una **noticia/catalizador** relevante hoy. Prioriza profundizar
   en los que más se mueven o tienen titulares; a los demás, solo el % del día.

   `SPY, SPX, CRM, AMZN, AMD, TSLA, INTC, IBM, UFO, STM, COIN, NOW, MU, MRVL,
   PLTR, QS, IREN, MSFT, NVDA, CRWV, SPCX, NFLX, CBRS`

5. **A vigilar hoy**: datos económicos programados, discursos de la Fed,
   earnings destacados (marca si alguno es de un ticker del portafolio).

## Salida — escribe EXACTAMENTE dos archivos (usa la herramienta Write)

No imprimas el brief en la conversación; SOLO escribe los archivos.

### Archivo 1: `output/brief_email.html`

Fragmento HTML autocontenido (SIN `<html>`/`<head>`/`<body>`), CSS inline
limpio, legible en Gmail (fondo claro). Estructura (español):

- Título: `Brief de Mercado — <fecha de hoy en español>`
- Insignia de **sesgo** (Risk-On / Risk-Off / Mixto) + una frase.
- **Índices**: SPY, QQQ, VIX, 10Y (niveles + lectura).
- **Noticias macro** (Yahoo Finance / CNBC): 3-5 viñetas (titular en negrita +
  por qué importa).
- **Trump hoy**: 2-4 viñetas de impacto de mercado (o "sin novedad relevante").
- **Tu portafolio** (educativo): una **tabla** con columnas
  `Ticker | Último | % Día | Nivel/nota`. Incluye todos los tickers; en la
  columna nota, pon la noticia/catalizador si lo hay, o un nivel clave, o "—".
  Ordena por mayor movimiento del día. Encabezado recordando que es educativo.
- **A vigilar hoy**: catalizadores / datos / earnings.
- Pie: `Herramienta educativa — no es asesoría financiera.` + marca de tiempo.

Usa números reales; "n/d" si falta un dato. Que sea escaneable.

### Archivo 2: `output/brief_whatsapp.txt`

Texto plano, ESPAÑOL, **menos de 850 caracteres** (límite duro), sin HTML.
Incluye, en este orden y muy conciso:
- Línea inicial: `📊 Brief <fecha>` + sesgo.
- SPY/QQQ (nivel clave), VIX, 10Y en una o dos líneas.
- La **noticia** más importante (1 línea).
- **Trump**: 1 línea si hay algo relevante (si no, omite).
- **Portafolio**: SOLO los 3-5 tickers TUYOS que más se movieron hoy (ticker,
  % día, y motivo si lo hay). No los listes todos.
- Cierre: `No es asesoría financiera.`

## Reglas

- Nunca inventes precios ni cifras; marca lo desconocido como n/d.
- Nunca des recomendaciones de compra/venta. Solo datos, niveles y contexto.
- Ambos archivos deben escribirse aunque falte algún dato. Todo en español.
