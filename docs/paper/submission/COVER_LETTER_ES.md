# Carta de presentación — Project Ghost

**Revista de destino:** ACM Transactions on Software Engineering and
Methodology (TOSEM) — Regular Paper.

**Revistas alternativas (orden de preferencia):** IEEE Transactions
on Software Engineering (TSE), CAV (Computer Aided Verification),
FMCAD (Formal Methods in Computer-Aided Design).

**Manuscrito:** *Epistemic Safety Contracts as a Property Class for
Autonomous Agents: A Formalised Framework with Mechanical Proofs
and a Real-Telemetry Discrimination Experiment.*
Javier Menéndez Mateos. v0.2.5 (rondas 23–33, enero 2026).

---

Estimado Editor,

Le envío respetuosamente el manuscrito **Epistemic Safety Contracts
as a Property Class for Autonomous Agents** para que sea evaluado
como Regular Paper en TOSEM.

## Qué aportamos

El paper introduce los **contratos epistémicos de seguridad**
(epistemic safety contracts) como una clase de propiedades distinta
de (a) los predicados tipo STL sobre señales externas y (b) la
monitorización bayesiana de creencias tipo POMDP. Un contrato
epistémico de seguridad es una tripleta `(P, Q, V)` donde `P` y
`Q` son predicados sobre la **postura del propio agente bajo
incertidumbre** (drift detectado, creencia calibrada, recuperación
acotada), y `V` es una función pura verificadora sobre una
ejecución content-addressed.

Las **cuatro contribuciones principales** del paper:

1. **La clase de propiedades en sí.** Argumentamos que los
   contratos sobre la postura epistémica responden a preguntas
   que las clases existentes no responden: *"¿degradó el agente
   conservadoramente cuando dudó de su propia confianza?"*,
   *"¿volvió a actuar cuando la evidencia se restableció?"*,
   *"¿es su latencia de recuperación acotada?"*. La clase está
   formalizada en v0.2.5 como un Python `Protocol`
   (`EpistemicSafetyContract`) más un registro de los siete
   contratos shipped (BAUD-v1, ERUR-v1, ERUR-v2, MD-v1, RLB-v1,
   FPB-v1, FPB-v2).

2. **Siete contratos concretos con sus verificadores y pruebas.**
   Cada contrato está enunciado en un ADR vinculante (inmutable
   una vez aceptado), verificado por una función pura sobre un
   MCAP capturado, y probado por un test Hypothesis. Cinco de los
   siete tienen prueba mecánica adicional: el teorema de partición
   BAUD/ERUR y los Lemas 1–3 del RLB-v1 unbounded en Lean 4 (sin
   `mathlib`, axiomas limitados a `propext` y `Quot.sound`); BAUD,
   ERUR, MD, RLB a `W` acotado en TLC; RLB-v1 en
   `W ∈ {4, 8, 16}` mediante un barrido paramétrico TLC; el
   autómata contador de FPB-v1 en TLC. El hueco restante — el
   Lema 4 del RLB-v1 unbounded — se entrega como un `sorry`
   documentado en Lean y está reducido a un único paso inductivo
   load-bearing (ADR-0044 candidate).

3. **Un puente mecánico entre el verificador Python y la
   especificación TLA+.** Hasta v0.2.5 el paper reconocía un
   caveat *"Python ↔ TLA+ bridge by inspection"*. ADR-0043 +
   ADR-0046 lo cierran para 5 de los 7 contratos mediante un
   test Hypothesis-checked que re-implementa ambas semánticas
   independientemente desde sus fuentes respectivas y exige que
   coincidan en cada traza que Hypothesis pueda sintetizar dentro
   de los bounds. Los dos contratos restantes (ERUR-v2 y FPB-v2)
   se documentan como out-of-scope con razones.

4. **Un experimento de discriminación end-to-end sobre telemetría
   PX4 real.** Seis categorías de bug de la matriz de violación
   sintética se exercitan sobre tres ULogs PX4 SITL
   estructuralmente distintos. Con GT independiente del simulador
   activado automáticamente cuando los topics `vehicle_*_groundtruth`
   están presentes (ADR-0037, v0.2.5), la matriz de discriminación
   es 18/18 verde; 15/18 celdas aíslan la violación a la propiedad
   esperada. La única fila no aislada es una co-violación real
   entre BAUD-v1 y MD-v1 (calibrador con confianza inflada).

## Por qué ahora

La intersección de sistemas autónomos, runtime verification y
métodos formales ha producido excelente trabajo en cada uno de
los tres lados (monitorización STL/MITL; verificación POMDP de
creencias; pruebas estilo TLA+/TLAPS). Lo que falta es una clase
de propiedades que capture **cómo un agente debería relacionarse
con su propia incertidumbre** — la clase que nuestro paper
introduce e instancia con una implementación operativa, un formato
de ejecución content-addressed, siete verificadores, pruebas
mecánicas y un experimento sobre telemetría real.

## Por qué esta revista

TOSEM publica trabajo que combina contribuciones metodológicas
(aquí: la clase de propiedades) con sustancia de ingeniería
(aquí: la implementación, los siete verificadores, las pruebas
mecánicas, la disciplina de diseño basada en ADRs). Números
recientes han incluido papers sobre monitorización STL,
frameworks de runtime verification y verificación formal de
sistemas robóticos; nuestro paper se sitúa en la intersección de
estos tres ejes. TSE, CAV y FMCAD son alternativas que
consideraríamos en ese orden.

## Reproducibilidad

El código completo, fuentes del paper, ADRs, pruebas mecánicas y
scripts de reproducibilidad están públicos en
[github.com/JFHelvetius/ghost](https://github.com/JFHelvetius/ghost)
bajo licencia Apache-2.0. Tres documentos de nivel superior
hacen el artefacto navegable:

- [`INSTALL.md`](https://github.com/JFHelvetius/ghost/blob/main/INSTALL.md) —
  guía de instalación desde cero para Python, Java, Lean y
  tla2tools.
- [`REPRODUCE.md`](https://github.com/JFHelvetius/ghost/blob/main/REPRODUCE.md) —
  reproducción end-to-end de cada claim del paper (R1–R7, ~10
  minutos totales en un laptop moderno).
- [`AUDIT.md`](https://github.com/JFHelvetius/ghost/blob/main/AUDIT.md) —
  la tabla de mapping claim-a-artefacto: cada claim del paper
  emparejado con su test, ADR, prueba o experimento subyacente.

CI ejecuta el test suite completo (~1785 tests) más las specs
TLA+ en cada push, a través de una matriz Linux/Windows ×
Python 3.11/3.12. Las pruebas Lean se ejecutan localmente; un
job CI `lean-proofs` es el siguiente paso natural.

## Declaración sobre uso de herramientas de IA

Este paper se preparó con asistencia de Anthropic Claude AI como
asistente de programación y revisor editorial. **Las contribuciones
conceptuales, las definiciones formales de propiedades, los siete
contratos epistémicos de seguridad, el diseño experimental, el
enfoque de reproducibilidad y todas las decisiones finales son del
autor.** La IA se usó para generación de código bajo supervisión,
redacción de prosa técnica en inglés y traducción del paper a
español y chino. Todos los teoremas, claims, citas y referencias
bibliográficas fueron verificados independientemente por el autor
contra sus fuentes primarias antes de la submission. El autor
asume responsabilidad completa por el contenido del paper.

## Declaración de novedad

Este trabajo no ha sido publicado ni enviado a publicación a
ninguna otra revista. No declaramos conflictos de intereses.

<!-- PENDIENTE COMPLETAR ANTES DE ENVIAR A TOSEM:
     Tras subir el preprint a arXiv, añadir aquí la frase:
     "Un preprint con los resultados v0.2.5 está disponible en
     arxiv.org/abs/XXXX.XXXXX y es la versión correspondiente a
     esta submission."
     Sustituir XXXX.XXXXX por el arXiv ID real. -->
[_PENDIENTE: añadir línea con arXiv ID cuando esté publicado._]

## Agradecimientos

La idea de este trabajo surgió durante el desarrollo de Ghost. Lo que comenzó como un proyecto centrado en simulación y verificación reproducible evolucionó gradualmente hacia una pregunta más fundamental: no solo si un agente actúa correctamente, sino cómo debería comportarse cuando deja de confiar en sus propias creencias sobre el entorno. Esa pregunta llevó a la definición de los contratos de seguridad epistémica propuestos en este artículo.

El proyecto fue desarrollado durante múltiples ciclos de implementación, experimentación y revisión conceptual. A medida que avanzaba el trabajo, se hizo evidente que muchas propiedades relevantes para la seguridad no describían únicamente el estado del entorno, sino también la relación del agente con su propia incertidumbre. Este cambio de perspectiva terminó convirtiéndose en la contribución central del trabajo.

Agradecemos al editor y revisores su tiempo y esperamos que el
paper alcance la barra de calidad.

Atentamente,

Javier Menéndez Mateos
*Independiente*
jfhelvetius@gmail.com
[github.com/JFHelvetius](https://github.com/JFHelvetius)
