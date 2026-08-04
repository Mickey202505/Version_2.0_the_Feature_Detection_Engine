# Architecture

## Overview

The Feature Detection Engine (FDE) is a reusable computer vision library.

The engine receives a raster image from a host application and returns editable
golf feature geometry.

---

# Responsibilities

## Host Application

Responsible for:

- Displaying imagery
- Image selection
- Coordinate conversion
- Geometry editing
- Exporting results

---

## Feature Detection Engine

Responsible for:

- Image processing
- OpenCV operations
- Feature detection
- Polygon generation
- Confidence scoring

---

# Processing Pipeline

Host Application

↓

Image

↓

Feature Detection Engine

↓

OpenCV Processing

↓

Feature Detection

↓

Geometry Processing

↓

Editable Geometry

↓

Host Application

---

# Design Principles

- Clean Architecture
- SOLID
- Modular detectors
- Test Driven Development
- OpenCV hidden behind the public API
- Deterministic processing