---
name: write-e2e-tests
description: Instructions for how to effectively write end-to-end tests.
---

We have a stable foundation for introducing E2E tests with Playwright, and documentation for how to write them at @docs/contributors/writing-e2e-tests.md.

Before running E2E tests, our Docker services must be running. `inv up` will start up our containers and run them in the background.

`inv test-e2e` will run all E2E tests headlessly. The global setup automatically creates a `test_squarelet` database, restarts Django to use it, runs migrations, and seeds test data. After tests complete, the original Django service is restored and the test database is dropped.

`inv test-e2e --grep "org viewing"` will run only tests matching the given pattern.

When introducing new functionality, we follow a red/green TDD method. We should always add tests first expecting them to fail, while defining the shape of our inputs and outputs. Only then do we change or add functionality to pass the test.

When testing existing functionality, we want to ensure we obtain wide coverage. This means testing the expected, "happy" path a user will follow _and_ trying out edge cases and intentionally mocking error responses cases to test fallback handling.
