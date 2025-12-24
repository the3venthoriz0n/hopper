"""Prometheus metrics for the application"""
try:
    from prometheus_client import Counter, Gauge, REGISTRY
    
    # Upload metrics
    try:
        successful_uploads_counter = Counter(
            'hopper_successful_uploads_total',
            'Total number of successful video uploads'
        )
    except ValueError:
        successful_uploads_counter = REGISTRY._names_to_collectors.get('hopper_successful_uploads_total')
    
    try:
        failed_uploads_gauge = Gauge(
            'hopper_failed_uploads',
            'Number of failed video uploads'
        )
    except ValueError:
        failed_uploads_gauge = REGISTRY._names_to_collectors.get('hopper_failed_uploads')
    
    # Scheduler metrics
    try:
        scheduler_runs_counter = Counter(
            'hopper_scheduler_runs_total',
            'Total number of scheduler job runs',
            ['status']
        )
    except ValueError:
        scheduler_runs_counter = REGISTRY._names_to_collectors.get('hopper_scheduler_runs_total')
    
    try:
        scheduler_videos_processed_counter = Counter(
            'hopper_scheduler_videos_processed_total',
            'Total number of videos processed by scheduler'
        )
    except ValueError:
        scheduler_videos_processed_counter = REGISTRY._names_to_collectors.get('hopper_scheduler_videos_processed_total')
    
    # Cleanup metrics
    try:
        cleanup_runs_counter = Counter(
            'hopper_cleanup_runs_total',
            'Total number of cleanup job runs',
            ['status']
        )
    except ValueError:
        cleanup_runs_counter = REGISTRY._names_to_collectors.get('hopper_cleanup_runs_total')
    
    try:
        cleanup_files_removed_counter = Counter(
            'hopper_cleanup_files_removed_total',
            'Total number of files removed by cleanup job'
        )
    except ValueError:
        cleanup_files_removed_counter = REGISTRY._names_to_collectors.get('hopper_cleanup_files_removed_total')
    
    try:
        orphaned_videos_gauge = Gauge(
            'hopper_orphaned_videos',
            'Number of orphaned video files (files without database records)'
        )
    except ValueError:
        orphaned_videos_gauge = REGISTRY._names_to_collectors.get('hopper_orphaned_videos')
    
    try:
        storage_size_gauge = Gauge(
            'hopper_storage_size_bytes',
            'Storage size in bytes',
            ['type']
        )
    except ValueError:
        storage_size_gauge = REGISTRY._names_to_collectors.get('hopper_storage_size_bytes')
    
    # Auth metrics
    try:
        login_attempts_counter = Counter(
            'hopper_login_attempts_total',
            'Total number of login attempts',
            ['status', 'method']
        )
    except ValueError:
        login_attempts_counter = REGISTRY._names_to_collectors.get('hopper_login_attempts_total')
        
except ImportError:
    # Prometheus not available - create no-op metrics
    class NoOpCounter:
        def labels(self, **kwargs):
            return self
        def inc(self, value=1):
            pass
    
    class NoOpGauge:
        def labels(self, **kwargs):
            return self
        def inc(self, value=1):
            pass
        def set(self, value):
            pass
    
    successful_uploads_counter = NoOpCounter()
    failed_uploads_gauge = NoOpGauge()
    scheduler_runs_counter = NoOpCounter()
    scheduler_videos_processed_counter = NoOpCounter()
    cleanup_runs_counter = NoOpCounter()
    cleanup_files_removed_counter = NoOpCounter()
    orphaned_videos_gauge = NoOpGauge()
    storage_size_gauge = NoOpGauge()
    login_attempts_counter = NoOpCounter()
