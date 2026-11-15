# Carpeta de datos

Coloque aquí los archivos publicados por el equipo docente en el GES (descomprimidos, sin
subcarpetas intermedias):

```
datos/
├── tiendas.csv
├── familias.csv
├── historico_ventas.csv
├── feriados.csv
├── costos.csv
├── catalogo_errores.md      (opcional, documentación)
└── ejemplos/                (opcional, documentación)
```

Los contenedores montan esta carpeta en `/datos` en modo solo lectura. Su contenido está en
`.gitignore`: los datos no forman parte del repositorio ni de las imágenes.
