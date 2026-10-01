# PRD - Atajos de teclado para etiquetado rápido
Estado: completado
Creado: 30/9/26

## Resumen
Hoy: Existen atajos básicos para navegación, reproducción y reset de la selección, pero gran parte de la interacción todavía depende del mouse y no existe un flujo completo orientado a revisión rápida de grandes cantidades de audio.

Después: Las operaciones frecuentes de etiquetado pueden realizarse principalmente mediante teclado, reduciendo la cantidad de interacción con el mouse y acelerando la validación de cientos o miles de archivos.

## Historia
Hoy: El usuario puede utilizar `Left`, `Right`, `Space` y `R`, pero debe usar el mouse para varias acciones y no existe una acción única para confirmar una anotación y avanzar.

Después: El usuario puede escuchar, corregir, confirmar, navegar y realizar pequeños ajustes de los bordes utilizando atajos consistentes sin abandonar el flujo de revisión.

## Objetivos / No-Objetivos
O1. Incorporar `Enter` como acción Confirmar + Guardar + Siguiente.

O2. Incorporar ajustes finos por teclado sobre los límites de inicio y final.

O3. Diferenciar ajustes pequeños y grandes mediante modificadores como `Shift`.

O4. Evitar conflictos entre los shortcuts globales y widgets interactivos de Qt.

NO1. No eliminar la interacción mediante mouse.

NO2. No convertir todos los parámetros de Trim Settings en shortcuts.

NO3. No implementar todavía personalización completa de shortcuts por usuario.

NO4. No utilizar shortcuts que provoquen pérdida silenciosa de anotaciones.

## Como funciona hoy -> Como deberia funcionar
HOY                                                                             Después

No existe confirmación explícita                                                  `Enter` confirma la anotación, la guarda y avanza

Los bordes se modifican principalmente con mouse                                 Los bordes pueden ajustarse también con teclado

No hay dos escalas de ajuste                                                      Tecla normal realiza ajuste fino y `Shift` realiza ajuste mayor

## Mapa inicial de shortcuts
`Space` -> Play / Pause

`Left` -> Archivo anterior

`Right` -> Archivo siguiente

`R` -> Reset manual selection a automatic trim

`Enter` -> Confirmar anotación + guardar + siguiente archivo


`,` -> Mover borde inicial una unidad hacia la izquierda

`.` -> Mover borde inicial una unidad hacia la derecha

`Shift + ,` -> Mover borde inicial con paso mayor hacia la izquierda

`Shift + .` -> Mover borde inicial con paso mayor hacia la derecha

Se deberá definir una combinación equivalente para el borde final evitando ambigüedad con los controles anteriores.

## Parámetros iniciales sugeridos
Ajuste fino: 5 ms

Ajuste mayor: 25 ms

Los valores deberán mantenerse centralizados para poder modificarlos posteriormente sin alterar la lógica de los shortcuts.

## Criterios de aceptación
CA1. Todas las acciones frecuentes de revisión pueden realizarse sin utilizar el mouse, exceptuando ajustes arbitrarios de posición.

CA2. `Enter` guarda exactamente una anotación para el archivo actual y luego avanza.

CA3. Si se encuentra en el último archivo, `Enter` guarda la anotación sin intentar navegar fuera del proyecto.

CA4. Los ajustes por teclado nunca permiten `manual_start < 0`.

CA5. Los ajustes por teclado nunca permiten `manual_end > duration`.

CA6. Los ajustes nunca permiten `manual_start >= manual_end`.

CA7. Cada movimiento de borde actualiza inmediatamente la waveform y las líneas correspondientes del espectrograma.

CA8. Los shortcuts de reproducción no interfieren con la escritura dentro de `TrimSettingsDialog`.

CA9. Al abrir un diálogo modal, los shortcuts de anotación que puedan modificar estado no se ejecutan accidentalmente.

CA10. Los pasos temporales de ajuste están definidos en un único lugar del código y no como valores repetidos en múltiples callbacks.
