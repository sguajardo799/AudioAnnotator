# PRD - Mejora de datos presentados en UI e incorporación de STATUS
Estado: lanzado
Creado: 30/9/26

## Resumen
Hoy: Solo existe la visualización de waveform+spectrograma y botones de control
Despues: Se incorporan datos de tracking, audios sin ver y ya revisados, se muestra un contador y una barra de progreso

## Historia
Hoy: El usuario avanza sin conocer cuantos audios quedan, sin poder planificar/estimar su trabajo
Despues: El usuario tiene feedback del trabajo hecho puede cerrar y saber cuanto tiene pendiente.

## Objetivos / No-Objetivos
O1. Incorporar en la parte posterior un contador de archivos, asi como estado NOT_VIEWED y VIEWED
O2. Integrar parámetro de revisado y un booleano de modificado(IS_MODIFIED) en el esquema de la db de cada proyecto
NO1. Eliminar botones u opciones existenres

## Como funciona hoy -> Como deberia funcionar
HOY                                                                             Despues
Solo se puede ver archivo actual y estimar en base a nombre cuanto falta        Se puede visualizar el avance y monitorear