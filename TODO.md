# Project Tasks

This file tracks the upcoming tasks for the NoiseBuster project.
Always test if changes work correctly after completion.
Update documentation if its working correctly. 

## Task List

- 1. [ ] Integrate Gemini CLI with GitHub Actions/Runners to automate code standard checks and potentially solve GitHub issues. See [run-gemini-cli](https://github.com/google-github-actions/run-gemini-cli) for details.
  - **Workflow:** Create a new GitHub Actions workflow.
  - **Triggers:** The workflow will be triggered by pull requests and commits to the `main` branch.
  - **Commands:** Add recommended Gemini CLI commands to the workflow.
- 2. [ ] Add tests to the CI/CD pipeline that run when code is committed to `main` or a pull request is created.
  - **Workflow:** Create a new workflow.
  - **Command:** The workflow will run `pytest`.
  - **Scope:** The pipeline will run both unit and mock integration tests.

*Note: This list can be used as a basis for creating GitHub Issues.*