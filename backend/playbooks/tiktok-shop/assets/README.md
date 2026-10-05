# Assets TikTok Shop

## html_base.html — HTML universal base
Plantilla premium oscura que se entrega a ChatGPT en la Etapa 2.
Por dentro es un renderizador de datos: el diseño/CSS es FIJO y el contenido
vive en un array JavaScript `const ideas=[{scene,title,hook,voz,mov,cam,cta}]`.
Cambiar de campaña = cambiar ese array. Por eso el repo puede:
- renderizar el HTML él mismo (sin IA) a partir de un ideas.json, y
- PARSEAR el HTML que devuelve ChatGPT para extraer de vuelta el JSON
  (dual output humano/máquina — principio de `arquitectura.txt` §15).

Estado: el ejemplo de oro `ejemplos/gymshark_html_final.html` sirve de base
hasta extraer/limpiar la versión universal sin datos de Gymshark (Fase 1).
