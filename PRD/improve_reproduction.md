# PRD - Mejora del sistema de reproducción de audio
Estado: lanzado
Creado: 30/9/26

## Resumen
Hoy: La reproducción utiliza `sounddevice.play()` sobre la selección actual. Permite reproducir el segmento seleccionado, pero no existe control persistente de reproducción, pausa, reanudación, loop o cursor temporal.

Después: La reproducción utiliza un `sounddevice.OutputStream` persistente que permite controlar play, pause, resume y reproducción de la selección sin recrear la salida de audio en cada interacción. La interfaz entrega feedback de la posición actual de reproducción.

## Historia
Hoy: El usuario puede escuchar la región seleccionada, pero debe iniciar nuevamente la reproducción cada vez y no tiene feedback visual de la posición dentro del audio.

Después: El usuario puede reproducir y pausar rápidamente mientras ajusta los límites manuales, visualizar la posición actual y repetir una región para validar con precisión el inicio y final del utterance.

## Objetivos / No-Objetivos
O1. Reemplazar el uso directo de `sounddevice.play()` por un `sounddevice.OutputStream` persistente.

O2. Implementar Play, Pause y Resume sin reconstruir el stream en cada interacción.

O3. Mantener la reproducción limitada a la región manual seleccionada cuando se solicita Play Selection.

O4. Incorporar un cursor visual sincronizado con la posición de reproducción en waveform y espectrograma.

O5. Permitir reiniciar la reproducción desde el inicio de la selección manual.

O6. Permitir opcionalmente reproducir la región seleccionada en loop para facilitar la validación de bordes.

NO1. No implementar todavía edición destructiva del audio.

NO2. No implementar todavía reproducción de múltiples archivos o pistas simultáneas.

NO3. No realizar procesamiento pesado dentro del callback de audio.

NO4. No incorporar todavía inferencia de modelos durante la reproducción.

## Como funciona hoy -> Como deberia funcionar
HOY                                                                             Después

`sd.play()` crea/inicia la reproducción de cada segmento                           Existe un `OutputStream` persistente administrado por `AudioPlayer`

Solo existe reproducción                                                         Existen Play, Pause, Resume y Stop

La reproducción comienza nuevamente cada vez                                     La posición de reproducción puede mantenerse al pausar y reanudar

No existe indicador temporal                                                      Un cursor muestra la posición actual en waveform y espectrograma

La selección define únicamente qué segmento enviar a `sd.play()`                 El reproductor utiliza `manual_start` y `manual_end` como límites activos

No existe loop                                                                    La selección puede reproducirse repetidamente de forma opcional

La GUI no conoce el progreso de reproducción                                      `AudioPlayer` expone el estado y posición para actualizar la GUI

## Criterios de aceptación
CA1. `AudioPlayer` mantiene un `OutputStream` reutilizable durante la sesión.

CA2. Presionar Play reproduce desde el comienzo de la región manual cuando no existe una reproducción pausada.

CA3. Presionar Pause detiene temporalmente el avance sin perder la posición actual.

CA4. Resume continúa desde la posición pausada.

CA5. Al alcanzar `manual_end`, la reproducción se detiene o vuelve a `manual_start` si Loop está activo.

CA6. El cursor visual avanza durante la reproducción y permanece sincronizado de forma perceptualmente correcta.

CA7. Cambiar de archivo detiene la reproducción anterior y reinicia el estado del reproductor.

CA8. Mover los límites manuales con la reproducción detenida actualiza los límites utilizados en el siguiente Play.

CA9. El callback de `OutputStream` no realiza lectura de archivos, cálculo de espectrograma ni otras operaciones bloqueantes.