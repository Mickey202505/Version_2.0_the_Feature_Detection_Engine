# Architectural Decision Record (ADR)

---

## ADR-001

Decision:

Restart project using OpenCV.

Status:

Accepted

Reason:

OpenCV provides a robust, well-tested computer vision framework and reduces the
need to implement low-level image processing algorithms from scratch.

---

## ADR-002

Decision:

Feature Detection Engine will be a reusable library.

Status:

Accepted

---

## ADR-003

Decision:

Host application is responsible for imagery and coordinate conversion.

Status:

Accepted

---

## ADR-004

Decision:

Public API will not expose OpenCV types.

Status:

Accepted

---

## ADR-005

Decision:

Development will follow Test Driven Development.

Status:

Accepted

---

## ADR-006

Decision:

Green Fringe is generated immediately after Green detection.

Status:

Accepted

Reason:

The fringe depends directly on the green geometry and must exist before bunker
clipping.

---

## ADR-007

Decision:

The engine will use deterministic computer vision.

Status:

Accepted

Reason:

The project intentionally avoids machine learning and AI to ensure consistent,
repeatable, and explainable results.

---

## ADR-008

Decision:

Each detected feature shall contain a unique identifier and confidence score.

Status:

Accepted