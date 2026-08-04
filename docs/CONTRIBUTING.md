# Contributing to the Feature Detection Engine (FDE)

Thank you for contributing to the Feature Detection Engine project.

This project follows a documentation-first development process. The goal is to
produce a professional, maintainable, and thoroughly tested computer vision
library for detecting golf course features from satellite and aerial imagery.

---

# Project Principles

Every contribution should follow these principles:

- Keep the design simple.
- Prefer readability over clever code.
- Follow SOLID principles.
- Follow Clean Architecture.
- Use deterministic algorithms.
- No machine learning.
- No artificial intelligence.
- Test Driven Development (TDD).
- Keep the public API stable.
- Hide OpenCV implementation details behind the FDE API.

---

# Before You Start

Please read the following documents before making changes:

- HANDBOOK.md
- ARCHITECTURE.md
- ROADMAP.md
- DECISIONS.md
- PROJECT_START.md

These documents are the authoritative source for project design.

---

# Development Workflow

Every new feature should follow this process.

1. Review the handbook.
2. Create or update tests.
3. Write the minimum code required.
4. Make all tests pass.
5. Refactor if necessary.
6. Update documentation.
7. Commit changes.

---

# Test Driven Development

The project follows Test Driven Development.

Workflow:

1. Write a failing test.
2. Verify the test fails.
3. Implement the minimum solution.
4. Make the test pass.
5. Refactor.
6. Repeat.

Production code should never be written without corresponding tests.

---

# Branch Naming

Use descriptive branch names.

Examples:

```
feature/green-detector

feature/green-fringe

feature/bunker-detector

bugfix/polygon-offset

docs/handbook-update

refactor/geometry-library
```

---

# Commit Messages

Follow this format.

```
type: short description
```

Examples:

```
feat: add green detector

feat: implement fringe clipping

fix: correct polygon winding

refactor: simplify geometry pipeline

docs: update handbook

test: add polygon offset tests
```

Common commit types:

- feat
- fix
- docs
- refactor
- test
- chore

---

# Pull Requests

Every pull request should:

- Have a clear title.
- Describe the purpose.
- Reference related issues if applicable.
- Include new tests.
- Update documentation where necessary.

Pull requests should remain focused on a single logical change.

---

# Coding Standards

Use modern TypeScript.

Requirements:

- Strict mode enabled.
- No implicit any.
- Explicit public return types.
- Prefer readonly.
- Prefer immutable data.
- Avoid global state.
- Prefer composition over inheritance.

---

# OpenCV

OpenCV is an internal implementation detail.

Do not expose OpenCV classes or data structures through the public API.

All OpenCV usage should remain inside the core implementation.

---

# Detector Design

Each detector should have a single responsibility.

Typical structure:

```
Detector

↓

Image Processing

↓

Candidate Detection

↓

Geometry Generation

↓

Confidence Calculation

↓

Return Result
```

Each detector should be independently testable.

---

# Geometry Standards

Generated polygons should:

- Be valid.
- Be editable.
- Avoid self-intersections.
- Maintain consistent winding order.
- Preserve topology.

The geometry pipeline should be shared across detectors whenever possible.

---

# Green Fringe

The green fringe is generated immediately after the green.

Rules:

- Offset exactly 600 mm.
- Preserve polygon topology.
- Clip around bunkers where necessary.
- Remain editable.

---

# Documentation

Documentation is part of the project.

Whenever behaviour changes, update the relevant documentation.

Possible documents include:

- HANDBOOK.md
- ARCHITECTURE.md
- ROADMAP.md
- PROGRESS.md
- DECISIONS.md
- CHANGELOG.md

---

# Architectural Decisions

Any significant architectural change should be recorded in:

```
DECISIONS.md
```

Include:

- Decision
- Status
- Reason
- Consequences

---

# Progress Tracking

Completed work should be recorded in:

```
PROGRESS.md
```

Major milestones should also update:

```
CHANGELOG.md
```

---

# Testing

Before committing, the following commands must succeed.

```bash
pnpm install

pnpm exec tsc --build

pnpm run test
```

No pull request should be merged with failing builds or failing tests.

---

# Definition of Done

A task is considered complete only when:

- Code compiles successfully.
- All tests pass.
- Documentation is updated.
- New tests have been added where appropriate.
- Code follows project standards.
- No known regressions exist.

---

# Reporting Issues

Bug reports should include:

- Description
- Steps to reproduce
- Expected behaviour
- Actual behaviour
- Environment
- Screenshots if applicable

---

# Project Philosophy

The Feature Detection Engine is designed to be:

- Reliable
- Predictable
- Deterministic
- Maintainable
- Well documented
- Easy to extend

The project values clarity over complexity and correctness over premature
optimisation.

Every contribution should help move the project toward a stable, professional,
and production-ready Feature Detection Engine.