"""
> Why: Register background task modules without coupling workers to API startup.
> Throughput: Task throughput depends on job implementations and worker concurrency.
> Dependencies: The configured Celery application.
"""
