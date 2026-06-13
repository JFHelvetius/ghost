# Versión española del paper (uso interno)

Esta carpeta contiene una traducción al español del paper técnico
canónico [`docs/paper/project_ghost_v0_2.md`](../project_ghost_v0_2.md)
para uso del autor y de colaboradores hispanohablantes.

## Archivos

| Archivo | Propósito |
|---|---|
| [`proyecto_ghost_v0_2_ES.md`](proyecto_ghost_v0_2_ES.md) | Traducción del paper |
| `README.md` | Este archivo |

## Política de divergencia

**La versión inglesa es canónica.** Es la que se sube a arXiv y la que
se adapta para FMAS 2026 / RV 2027. Cualquier divergencia entre las
dos versiones debe resolverse a favor de la inglesa.

Cuándo actualizar la versión española:

- Cuando la versión inglesa reciba una actualización mayor (nueva
  sección, contribución renombrada, tabla rehecha).
- Cuando un colaborador hispanohablante reporte que la traducción
  contiene un error.
- Antes de cada release (asegurar que las versiones citadas matchean).

Cuándo **no** actualizar:

- Pequeños cambios de prosa en la versión inglesa que no afectan el
  contenido técnico — la versión española puede quedar levemente
  desfasada en estilo sin perder valor.

## Qué se traduce

- Prosa explicativa, motivación, scope.
- Subsecciones de §8 Evaluation (en versión resumida; los números
  exactos se mantienen en inglés y la tabla canónica vive en la
  versión inglesa).
- Capítulos §1 (Introducción), §2 (Background), §9 (Limitations),
  §10 (Future work), §11 (Conclusión) — traducciones completas.

## Qué NO se traduce

- Nombres de propiedades: BAUD-v1, ERUR-v1, MD-v1, RLB-v1, FPB-v1.
- Nombres de specs TLA+: `BaudErur.tla`, `Rlb.tla`, `Fpb.tla`,
  `Rlb_unbounded.tla`.
- Nombres de invariantes: `INV_BAUD`, `INV_ERUR`, `INV_PARTITION`,
  `INV_RLB`, etc.
- Nombres de policies: `MahalanobisDowngradePolicy`,
  `EWMADowngradePolicy`, etc.
- Snippets de código bash o Python.
- Rutas de archivos del repositorio.
- Theorem 1 statement y prueba — copiados verbatim, solo la prosa
  alrededor está en español.
- Referencias bibliográficas — formato canónico inglés.

## Uso recomendado

- **Para colaboradores hispanohablantes:** leer la versión española
  primero para entender la motivación y luego la inglesa para
  detalles cuantitativos.
- **Para presentaciones internas en español:** usar esta como base
  de slides; copiar el inglés solo donde sea más preciso.
- **Para arXiv / FMAS / RV submission:** ignorar esta carpeta. Usar
  [`docs/paper/arxiv/`](../arxiv/).
