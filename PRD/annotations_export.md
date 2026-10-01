# PRD - Exportación de anotaciones
Estado: pendiente
Creado: 1/10/26

## Resumen
Hoy: Las anotaciones se almacenan internamente en SQLite dentro del proyecto y pueden ser utilizadas por la aplicación, pero no existe una forma directa de exportarlas a un formato orientado a análisis o entrenamiento.

Después: El usuario puede exportar las anotaciones del proyecto desde la interfaz a CSV y opcionalmente Parquet, incluyendo límites automáticos, límites manuales, diferencias temporales, estado de revisión y metadatos necesarios para análisis posterior.

## Historia
Hoy: Para analizar las anotaciones fuera de la aplicación sería necesario consultar directamente la base SQLite o crear scripts adicionales.

Después: El usuario puede generar desde la aplicación un dataset tabular listo para abrir en Python, R, Excel u otras herramientas, manteniendo una representación reproducible del estado actual de las anotaciones.

## Objetivos / No-Objetivos
O1. Incorporar una acción `File → Export Annotations...`.

O2. Permitir exportar todas las anotaciones almacenadas en SQLite.

O3. Exportar inicialmente a CSV.

O4. Dejar preparada la implementación para soportar Parquet posteriormente.

O5. Mantener una fila por archivo anotado.

O6. Incluir los límites automáticos y manuales en segundos.

O7. Incluir las diferencias `delta_start_ms` y `delta_end_ms`.

O8. Incluir información suficiente para asociar cada anotación con su archivo original.

O9. Permitir seleccionar la ubicación y nombre del archivo exportado.

O10. Mantener la exportación desacoplada de la interfaz gráfica.

NO1. No modificar los archivos WAV durante la exportación.

NO2. No generar automáticamente audios recortados.

NO3. No reemplazar SQLite como almacenamiento principal.

NO4. No realizar todavía particiones train/validation/test.

NO5. No incorporar todavía cálculo de métricas agregadas durante la exportación.

## Como funciona hoy -> Como deberia funcionar
HOY                                                                             Después

Las anotaciones permanecen únicamente en `annotations.db`                        Pueden exportarse desde `File → Export Annotations...`

El análisis externo requiere consultar SQLite manualmente                         Se genera un archivo tabular listo para análisis

La base de datos es el formato principal de persistencia                          SQLite continúa siendo la fuente de verdad y CSV/Parquet son exportaciones

No existe selección de destino                                                    El usuario selecciona ruta y nombre mediante diálogo

No existe formato de intercambio explícito                                        CSV se soporta inicialmente y Parquet puede añadirse después

La estructura exportada depende implícitamente del esquema SQLite                 Se define explícitamente un esquema estable de columnas exportadas

## Esquema inicial de exportación
El CSV exportado deberá contener inicialmente:

`filename`

`duration`

`sample_rate`

`auto_start`

`auto_end`

`manual_start`

`manual_end`

`delta_start_ms`

`delta_end_ms`

`updated_at`

Cuando se implemente el estado de revisión deberá incorporarse además:

`reviewed`

Y cuando se persista la configuración utilizada por el detector podrá añadirse:

`trim_config_id`

o la referencia equivalente utilizada por el esquema SQLite.

## Flujo de usuario
El usuario abre un proyecto.

Realiza o modifica anotaciones.

Selecciona:

`File → Export Annotations...`

La aplicación abre un diálogo de destino.

El usuario selecciona, por ejemplo:

`annotations_export.csv`

La aplicación consulta SQLite y genera el archivo.

La base `annotations.db` no se modifica.

## Comportamiento de la exportación
La exportación debe representar el estado actual de SQLite en el momento en que se ejecuta.

Si un archivo fue corregido varias veces, solamente debe aparecer su anotación más reciente, dado que SQLite mantiene una única fila por `filename`.

El orden recomendado inicialmente es por `filename` para obtener resultados deterministas entre exportaciones.

## Arquitectura propuesta
La lógica de exportación no debe implementarse directamente en `MainWindow`.

Se puede extender `AnnotationStore` con una operación de lectura:

`get_all()`

y utilizar un componente separado:

`AnnotationExporter`

Flujo:

`MainWindow`
↓
`AnnotationStore.get_all()`
↓
`AnnotationExporter`
↓
CSV / Parquet

De esta forma la GUI solo coordina la acción y la selección del destino.

## Validaciones
V1. No permitir exportación si no existe un proyecto abierto.

V2. Si no existen anotaciones, informar al usuario y no generar un archivo vacío accidentalmente.

V3. La ruta seleccionada no debe modificar `annotations.db`.

V4. Los valores temporales deben exportarse como números y no como strings formateados.

V5. La exportación debe conservar suficiente precisión para reconstruir los límites temporales.

V6. El archivo resultante debe contener exactamente una fila por anotación almacenada.

## Criterios de aceptación
CA1. Existe `File → Export Annotations...`.

CA2. La opción permanece deshabilitada si no hay proyecto abierto.

CA3. Al ejecutarla se abre un diálogo para seleccionar el destino.

CA4. Se puede generar un CSV válido directamente desde las anotaciones SQLite.

CA5. Cada `filename` aparece como máximo una vez.

CA6. Los valores `auto_start`, `auto_end`, `manual_start` y `manual_end` se exportan en segundos.

CA7. `delta_start_ms` y `delta_end_ms` coinciden con los valores almacenados en SQLite.

CA8. La exportación no modifica ninguna anotación existente.

CA9. Repetir la exportación sin modificar la base produce el mismo contenido salvo metadatos externos del archivo.

CA10. La lógica de serialización no depende de widgets Qt y puede utilizarse posteriormente desde scripts o pruebas automatizadas.

## Evolución posterior
La misma funcionalidad podrá extenderse posteriormente con:

- Exportación a Parquet.
- Exportación solo de archivos revisados.
- Exportación filtrada por tipo de error.
- Inclusión de configuración del detector.
- Inclusión de métricas derivadas.
- Exportación de subconjuntos para entrenamiento.