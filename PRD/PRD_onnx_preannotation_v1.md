# PRD — Integración ONNX para preanotación de audio (V1)

**Estado:** implementado (V1; validación numérica sintética y regresión automatizada)  
**Fecha:** 08/10/2026  
**Repositorio:** https://github.com/sguajardo799/AudioAnnotator  
**Alcance:** inferencia ONNX local, UI no bloqueante, decodificación y persistencia separada de predicciones/correcciones.

## Resumen

### Decisiones concretadas durante implementación

- Paquete local: `model_packages/crnn_baseline-1.0.0/`; scripts, checkpoints e
  informes de entrenamiento retirados de la aplicación.
- Preferencias por usuario con `QSettings`; ONNX Runtime CPU obligatorio.
- Frontend mono por media, 16 kHz, sinc Hann (width 6, rolloff 0.99), log-Mel
  HTK de 64 bandas, FFT 400/hop 160, normalización sobre frames válidos.
- El modelo recibe padding a 6 s; entradas más largas se **truncan solo para
  inferencia** por decisión de producto. Playback y edición conservan el WAV completo.
- Decoder elige el intervalo más largo, primero en empates, y falla si no hay
  frames positivos. Esta política sustituye intencionalmente el fallback argmax
  de la referencia de entrenamiento.
- Navegación/cierre guardan únicamente borradores editados; Enter confirma
  `VIEWED`. Una selección completamente manual tiene fuente e ID de predicción nulos.
- Predicciones incluyen hash de audio y configuración canónica; nueva propuesta
  sobre un archivo revisado requiere aceptación para activarse sin cambiar manuales.
- Fixtures independientes de Torchaudio en `tests/fixtures/` verifican el
  frontend a 8, 16, 44.1 y 48 kHz sin PyTorch como dependencia runtime.

**Hoy:** AudioAnnotator emplea `estimate_trim()` de `smartaudiocrop/trim/detector.py` como propuesta heurística. Al cargar el WAV, `MainWindow.load_current_audio()` ejecuta `run_auto_trim()` y después `restore_annotation()`. `AnnotationStore` mantiene una fila por archivo en SQLite con `auto_start`, `auto_end`, `manual_start`, `manual_end`, `status` e `is_modified`. Los límites automáticos y manuales se muestran por separado en `AudioView`.

**Después:** El usuario puede elegir entre detector heurístico y CRNN ONNX para producir una propuesta de recorte, sin congelar PySide6. Se registra la predicción inmutable del modelo junto con su versión y configuración; los límites manuales continúan editables y separados. Reabrir un WAV o cambiar de motor nunca destruye una corrección anterior. La exportación permite identificar el origen de la propuesta y diferenciar predicciones de anotaciones revisadas.

## Historia de usuario

Como anotador, quiero seleccionar un modelo ONNX local para obtener el inicio y final estimados de una oración, ver su propuesta sobre waveform/espectrograma, corregir las cotas y guardar tanto la predicción original como el resultado revisado para reutilizar esos datos posteriormente.

## Objetivos / No-objetivos

**O1.** Soportar proveedor de recorte `heuristic` o `onnx_crnn` sin romper `estimate_trim()`.  
**O2.** Cargar un `.onnx` validado y su `model_manifest.json` y mostrar el modelo activo y versión.  
**O3.** Reproducir fielmente el frontend de entrenamiento y el decodificador de la validación (configuración tomada del manifest, no valores genéricos).  
**O4.** Ejecutar inferencia en un worker Qt sin bloquear reproducción, navegación ni interacción.  
**O5.** Mostrar resultado solo para el WAV/proyecto/versión de solicitud vigentes.  
**O6.** Persistir predicciones originales separadas de los límites editables; preservar estado de revisión.  
**O7.** Migrar esquemas SQLite existentes sin perder registros, manteniendo las interfaces de lectura vigentes.  
**O8.** Extender exportación CSV con procedencia, versión y estado de revisión sin destruir la compatibilidad de columnas existentes.  
**O9.** Incluir pruebas unitarias, de integración y de interfaz para los escenarios críticos.

**NO1.** No implementar active learning, ranking, calibración de confianza ni reentrenamiento dentro de la app.  
**NO2.** No recortar físicamente ni sobreescribir los WAV originales.  
**NO3.** No exigir GPU, CUDA ni PyTorch durante el uso de la app.  
**NO4.** No procesar miles de WAV en batch en segundo plano en esta V1.  
**NO5.** No inferir automáticamente sobre WAV con anotación manual existente al abrirlos.  
**NO6.** No introducir una segunda fuente de verdad para las anotaciones finales fuera de SQLite.

## Cambios esperados: hoy → después

| Aspecto | Hoy | V1 |
|---|---|---|
| Detector | `estimate_trim` heurístico | Selector heurística / ONNX CRNN |
| Ejecución | Cálculo durante `load_current_audio()` | ONNX asíncrono, con indicador de progreso/estado |
| Límites | `auto_*` + `manual_*` | Límites propuestos y editables con procedencia |
| Guardado | Un registro por WAV | Registro final por WAV + historial de predicciones inmutables |
| Revisado | `NOT_VIEWED` / `VIEWED` | Mismo estado, no se marca revisado al inferir |
| Exportación | CSV de cotas, estado y diferencias | Columnas actuales más proveedor, modelo y referencia a predicción |

## Contrato de modelo y preprocesamiento

**Entradas del paquete de modelo:** `model.onnx`, `model_manifest.json`, opcionalmente archivo de checksum/documentación. No asumir que cualquier modelo ONNX es compatible.

El manifest debe declarar y validar, al menos:

- `model_id`, `model_version`, `model_type` (para V1, `crnn_mask`), `input_name`, `output_name`, `input_shape` o descripción de ejes dinámicos, `sample_rate` de inferencia.
- `n_fft`, `win_length`, `hop_length`, `n_mels`, parámetros de Mel (`f_min`, `f_max`, `mel_scale`, `norm`), configuración de centrado/padding STFT, potencia/magnitud, transformación logarítmica y normalización/estandarización que efectivamente usó `dataset.py`.
- `threshold` (inicialmente 0.50 si así figura en la calibración), `bridge_ms` y método de decodificación exacto, incluidos offset de frames, política de selección de un único intervalo, y fallback sin frames positivos.
- `model_sha256` y `preprocessing_version`/`decoder_version` para trazabilidad.

**Regla:** no reutilizar directamente `smartaudiocrop/audio/analysis.py` como frontend del modelo: su STFT es para visualización y no garantiza equivalencia numérica con el log-Mel de entrenamiento. Implementar un `OnnxAudioPreprocessor` independiente que reciba audio cargado por `audio/loading.py` y produzca el tensor de entrada del modelo. Debe admitir mono/multicanal según la misma regla usada en entrenamiento, resampling, `float32`, y audios de duración variable. Evitar `torch`/`torchaudio` en dependencias runtime; usar NumPy/SciPy o una dependencia ligera, previa prueba de equivalencia.

**Invariantes de salida:** dos cotas finitas en segundos, `0 <= start < end <= duration` (o fallo explícito), un único intervalo. Mapear correctamente el eje temporal de salida y tener en cuenta límites reales de la señal. No aplicar un padding adicional por defecto.

**Validación del paquete:** rechazar carga por campos ausentes, ONNX incompatible, shape incorrecta, checksum inválido o configuración no soportada. Mostrar error legible y permitir volver a heurística sin pérdida de anotaciones.

## Arquitectura propuesta

Mantener desacoplamiento de UI y dominio:

```
MainWindow (selección, estado, signals/slots)
   │
   ├── ProjectSession / AnnotationStore (persistencia)
   │
   └── TrimService (orquestación)
         ├── HeuristicTrimProvider -> estimate_trim(...)
         └── OnnxTrimProvider
              ├── ModelPackage / manifest validator
              ├── OnnxAudioPreprocessor
              ├── onnxruntime.InferenceSession CPU
              └── TemporalDecoder -> TrimTimes

InferenceWorker (QObject movido a QThread o QRunnable + signal de resultados)
```

Nuevos módulos sugeridos: `smartaudiocrop/trim/providers.py`, `smartaudiocrop/trim/onnx_provider.py`, `smartaudiocrop/trim/onnx_preprocessing.py`, `smartaudiocrop/trim/decoder.py`, `smartaudiocrop/ui/inference_worker.py`. Los nombres pueden adaptarse al repositorio; evitar lógica de inferencia en `MainWindow`.

**Hilos:** creación/carga ONNX y ejecución del `InferenceSession` fuera del hilo GUI. Emitir `success(request_id, project_id, audio_id, result)` o `failure(...)`; nunca modificar widgets ni usar conexiones SQLite desde el worker. Asignar un token monotónico de solicitud y verificarlo antes de aplicar resultado. En cambio de archivo/proyecto o cierre, invalidar solicitudes pendientes y gestionar liberación de QThread de forma segura. No esperar a que termine la inferencia para navegar; ignorar resultados obsoletos.

## Interfaz y flujo de usuario

1. Añadir en `Trim` una opción de motor (`Heuristic` / `ONNX Model…`) y una acción para elegir el par ONNX/manifest y ver su versión. Persistir preferencia de selección a nivel de configuración de usuario/proyecto según convención de la app; no guardar ruta absoluta en cada anotación.
2. Con motor heurístico, conservar flujo actual de `Run Auto Trim` y `Trim Settings…`.
3. Con motor ONNX, mostrar `Run Pre-annotation` o reutilizar `Run Auto Trim` cambiando etiqueta/contexto. Al abrir un archivo sin anotación, la V1 puede iniciar la propuesta automáticamente si el modelo ya está cargado y el usuario habilita **Auto-run on open**; por defecto ejecutar por acción explícita para evitar procesamiento innecesario.
4. Mientras corre: mostrar `Inferring…`, deshabilitar solo la acción duplicada y mantener audio/playback/navegación funcional.
5. Al terminar, mostrar las cotas propuestas con las mismas marcas automáticas de `AudioView`, inicializar manuales **solo si no hay una anotación previa**; si ya existe, conservarla. Indicar `Propuesta: ONNX · crnn_v1` (o `Heuristic`).
6. El usuario ajusta manualmente y confirma. La app guarda la anotación final usando el flujo actual. `Reset manual trim` restaura la **propuesta activa** pero requiere acción explícita; nunca se ejecuta al navegar.
7. Si falla ONNX, informar el motivo, no inventar límites 0..duration como predicción del modelo ni registrar predicción exitosa; permitir fallback heurístico explícito.

**Advertencia de comportamiento existente:** `MainWindow.load_current_audio()` ejecuta `run_auto_trim()` antes de `restore_annotation()`; `save_annotation()` y la navegación realizan guardados automáticos. La integración debe diferenciar *propuesta generada* de *anotación confirmada*. Evitar que una propuesta aún no revisada se persista accidentalmente como `VIEWED` por navegar o cerrar.

## Persistencia SQLite y migración

Preservar `annotations` (una fila por `filename`) y los campos vigentes. Agregar metadatos mínimos por migración idempotente mediante `PRAGMA user_version` y `ALTER TABLE` cuando corresponda:

- `proposal_source TEXT` (`heuristic`, `onnx_crnn`, `legacy`, nullable para registros antiguos).
- `prediction_id INTEGER NULL` referencia a predicción seleccionada.
- Mantener `auto_start` y `auto_end` como cotas **de la propuesta seleccionada** para compatibilidad. `manual_start` y `manual_end` siguen siendo límites editados y `delta_*` diferencia respecto de esa propuesta.

Crear tabla de predicciones separada:

```sql
CREATE TABLE IF NOT EXISTS predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('onnx_crnn', 'heuristic')),
    model_id TEXT,
    model_version TEXT,
    model_sha256 TEXT,
    preprocessing_version TEXT,
    decoder_version TEXT,
    threshold REAL,
    bridge_ms REAL,
    predicted_start REAL NOT NULL,
    predicted_end REAL NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

**Orden transaccional:** una predicción sobre un WAV nuevo puede existir antes de que exista una anotación revisada. Por ello, en V1 `predictions.filename` no referencia por FK a `annotations.filename`; validar la existencia del archivo a nivel de aplicación. No crear anotaciones ficticiamente revisadas solo para satisfacer una FK. En una versión posterior puede introducirse una tabla `audio_files` independiente para integridad referencial.

Una inferencia exitosa inserta una predicción inmutable. `annotations.prediction_id` identifica la propuesta elegida; una nueva inferencia no sobrescribe correcciones históricas ni cambia por sí sola `status`. Si el usuario selecciona nueva propuesta para su anotación, actualizar `auto_*` y `delta_*` atómicamente, conservando `manual_*` salvo aceptación explícita. Datos legacy deben conservar todos sus campos y abrirse sin migración manual. No duplicar predicciones en cada navegación si existe una reutilizable para el mismo archivo+versión+configuración; `Force re-run` permite crear nueva entrada deliberadamente.

**Crítico:** actualmente `AnnotationStore.save()` aplica UPSERT sobre todas las cotas. Refactorizar el guardado para que navegación/cierre no reemplace propuestas persistidas o correcciones sin intención, y para diferenciar guardado técnico del evento de confirmación (`VIEWED`).

## Exportación CSV

Extender `AnnotationExporter` conservando las columnas actuales y su semántica. Anexar `proposal_source`, `prediction_id`, `model_id`, `model_version`, `model_sha256`, `threshold`, si existe, y `reviewed` derivado del estado actual. **No tratar propuestas sin revisión como ground truth** en exportación para entrenamiento: `manual_start/end` de filas `NOT_VIEWED` deben ser explícitamente no verificadas (aunque tengan valores sugeridos). La exportación de historial completo de predicciones no forma parte de V1; los datos quedan en SQLite para V2.

## Manejo de errores y seguridad de datos

- ONNX/manifest ausente o corrupto → diálogo claro, motor heurístico disponible.
- WAV inválido, vacío, no finito o sin actividad detectable → mensaje y ninguna predicción exitosa persistida.
- Resultados de un archivo anterior → descartar por token/identidad.
- Reprocesamiento de anotación revisada → no sobrescribir sin confirmación explícita.
- Cierre de app durante inferencia → limpieza segura; la última corrección ya confirmada permanece intacta.
- Falla SQLite → rollback y aviso, sin actualizar estado visual como guardado.
- Cualquier ruta de ONNX es local y explícita; no descarga automática ni ejecución de código arbitrario desde un paquete de modelo. Registrar errores sin imprimir audio ni datos personales.

## Pruebas

**Unitarias**
- Manifest válido/inválido y compatibilidad de shapes.
- Preprocesamiento equivalente al de entrenamiento con fixtures de WAV (tolerancias numéricas definidas).
- Decodificación de logits a cotas con casos extremos: no positivos, pausas, extremos y duración variable.
- Migración desde SQLite anterior, idempotencia e integridad de filas.
- Anotaciones no revisadas y revisadas; actualización de propuesta sin sobrescribir manuales.

**Integración**
- ONNX Runtime CPU vs referencia PyTorch exportada: diferencias de logits y cotas dentro de tolerancias previamente validadas con audios de validación.
- Mismo resultado desde la app y `export_onnx.py` con idéntico audio/configuración.
- Apertura, inferencia, edición, confirmación, cierre y reapertura conservan tanto predicción original como corrección manual.
- Dos solicitudes sucesivas con navegación rápida: solo la correspondiente al archivo visible actualiza UI.
- Exportación CSV legacy y columnas nuevas, con estado correcto.

**UI**
- Reproducción y navegación siguen respondiendo durante inferencia.
- La heurística existente sigue funcionando sin ONNX instalado/configurado, salvo dependencia instalada en entorno cuando se selecciona ONNX.
- No cambia a `VIEWED` por inferencia, apertura, navegación o cierre sin confirmación.

## Criterios de aceptación

**CA1.** El usuario puede cargar un `.onnx` acompañado de manifest válido y seleccionar motor ONNX/heurístico.  
**CA2.** ONNX Runtime CPU produce una propuesta de una sola ventana en segundos dentro de la duración original.  
**CA3.** La equivalencia con la implementación PyTorch de referencia se mantiene dentro de las tolerancias verificadas en validación.  
**CA4.** La GUI no se bloquea durante inferencia y las solicitudes obsoletas no actualizan otro WAV.  
**CA5.** Waveform/espectrograma muestran la propuesta automática y la selección manual por separado.  
**CA6.** El usuario puede corregir y guardar; al reabrir, su edición manual no es reemplazada por el modelo.  
**CA7.** Se almacenan fuente, versión, parámetros relevantes y cotas originales de cada predicción.  
**CA8.** Migración SQLite no elimina registros existentes, mantiene una anotación actual por WAV y no exige rehacer proyectos.  
**CA9.** `NOT_VIEWED` no se considera dato revisado y la mera inferencia no incrementa el contador de revisados.  
**CA10.** CSV conserva columnas existentes y expone procedencia y revisión para filtrar etiquetas en entrenamiento.  
**CA11.** Errores de carga/inferencia no producen propuestas falsamente válidas ni pérdidas de anotaciones.  
**CA12.** La ejecución de pruebas existentes de `tests/` no presenta regresiones relevantes.

## Orden de implementación sugerido

1. **Persistencia y migración:** tests sobre DB antigua; separar confirmación de autosave.
2. **Runtime independiente:** manifest, log-Mel fiel, `InferenceSession`, decodificación y pruebas numéricas.
3. **Worker Qt:** señales con identificador de solicitud, cancelación lógica y pruebas de concurrencia.
4. **Integración MainWindow/AudioView:** selector de motor, ejecución, estado visual y restauración.
5. **Exportación y QA end-to-end:** procedencia en CSV, pruebas de cierre/reapertura y regresión de heurística.

## Dependencias y artefactos

- `onnxruntime` CPU para inferencia, `numpy`, `scipy`, `soundfile`, PySide6 ya presentes; evitar agregar `torch` o `torchaudio` al runtime.
- Paquete exportado y validado: `model.onnx` + `model_manifest.json` (ajustar estructura del manifest según el `export_onnx.py` real antes de implementar el parser).
- Datos de prueba: WAV de validación con cotas PyTorch/ONNX de referencia y al menos un proyecto SQLite previo a migración.

## Evolución fuera de alcance (V2)

Incertidumbre por frontera, variación de umbral, fragmentación, validación/calibración de riesgo, selección activa de audios, fine-tuning, reentrenamiento y exportación completa del historial de predicciones. V1 conserva desde ya metadatos y predicciones originales necesarios para esas funciones.
