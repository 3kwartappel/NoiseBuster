# AI Development Guidelines

This document outlines best practices for AI-assisted development on this project to ensure consistency, quality, and compatibility with various AI models.

## Core Principles

- **Create Tests:** When implementing a new feature, create corresponding tests whenever possible. This ensures code quality and provides a safety net for future changes.
- **Secret-Scanning:** Always check for secrets before pushing code. The AI assistant should warn if any sensitive information (API keys, passwords, etc.) is about to be committed.
- **Model Agnostic:** All workflows, prompts, and standards should be designed to be compatible with other AI models (e.g., GitHub Copilot) to avoid vendor lock-in.
