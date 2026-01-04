"""Scheduler module for running tasks at specified times."""
import logging
import asyncio
import time
import threading
from datetime import datetime
from typing import List, Callable, Awaitable, Optional
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

logger = logging.getLogger(__name__)

# Type alias for async task function
TaskFunction = Callable[[], Awaitable[None]]


class TaskScheduler:
    """Scheduler for running parsing tasks."""
    
    # Job configuration
    MAX_INSTANCES = 1
    COALESCE = True
    MISFIRE_GRACE_TIME = 300  # 5 minutes
    
    def __init__(self, times: List[str], timezone: str = "UTC"):
        """Initialize scheduler.
        
        Args:
            times: List of times in "HH:MM" format
            timezone: Timezone string (e.g., "UTC", "Europe/Moscow")
        """
        self._times = times
        self._timezone = pytz.timezone(timezone)
        self._scheduler = BlockingScheduler(timezone=self._timezone)
        self._task_function: Optional[TaskFunction] = None
        self._thread: Optional[threading.Thread] = None
    
    @property
    def scheduler(self) -> BlockingScheduler:
        """Get underlying scheduler."""
        return self._scheduler
    
    @property
    def is_running(self) -> bool:
        """Check if scheduler is running."""
        return self._scheduler.running
    
    def set_task(self, task_function: TaskFunction) -> None:
        """Set the task function to run."""
        self._task_function = task_function
    
    @staticmethod
    def parse_time(time_str: str) -> tuple:
        """Parse time string 'HH:MM' into (hour, minute)."""
        try:
            parts = time_str.split(':')
            if len(parts) != 2:
                raise ValueError()
            hour, minute = int(parts[0]), int(parts[1])
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError()
            return hour, minute
        except (ValueError, IndexError):
            raise ValueError(f"Invalid time format: '{time_str}'. Expected 'HH:MM'")
    
    def _add_jobs(self) -> None:
        """Add scheduled jobs for each time."""
        for time_str in self._times:
            hour, minute = self.parse_time(time_str)
            
            trigger = CronTrigger(
                hour=hour,
                minute=minute,
                day='*',
                timezone=self._timezone
            )
            
            self._scheduler.add_job(
                self._execute_task,
                trigger=trigger,
                id=f"task_{time_str.replace(':', '')}",
                replace_existing=True,
                max_instances=self.MAX_INSTANCES,
                coalesce=self.COALESCE,
                misfire_grace_time=self.MISFIRE_GRACE_TIME
            )
            
            logger.info(f"Scheduled task for {time_str} ({self._timezone})")
    
    def _execute_task(self) -> None:
        """Execute the task function."""
        current_time = datetime.now(self._timezone)
        
        logger.info("=" * 60)
        logger.info(f"RUNNING SCHEDULED TASK at {current_time}")
        logger.info("=" * 60)
        
        if not self._task_function:
            logger.error("Task function is not set!")
            return
        
        try:
            asyncio.run(self._task_function())
            logger.info("=" * 60)
            logger.info(f"Task completed at {datetime.now(self._timezone)}")
            logger.info("=" * 60)
        except Exception as e:
            logger.error(f"Error in task: {e}", exc_info=True)
            # Don't re-raise - scheduler should continue
    
    def _run_scheduler_loop(self) -> None:
        """Run scheduler in thread."""
        try:
            self._scheduler.start(paused=False)
        except (KeyboardInterrupt, SystemExit):
            logger.info("Scheduler interrupted")
    
    def start(self) -> None:
        """Start the scheduler."""
        if not self._task_function:
            raise ValueError("Task function not set. Call set_task() first.")
        
        self._add_jobs()
        
        # Start in background thread
        logger.info("Starting scheduler...")
        self._thread = threading.Thread(
            target=self._run_scheduler_loop,
            daemon=False
        )
        self._thread.start()
        
        # Wait for scheduler to initialize
        time.sleep(1)
        
        # Log status
        self._log_status()
    
    def _log_status(self) -> None:
        """Log scheduler status and next run times."""
        jobs = self._scheduler.get_jobs()
        logger.info(f"Total jobs scheduled: {len(jobs)}")
        
        for job in jobs:
            if job.next_run_time:
                logger.info(f"Next run for '{job.id}': {job.next_run_time}")
            else:
                logger.warning(f"Job '{job.id}' has no next run time!")
        
        if self._scheduler.running:
            logger.info("✓ Scheduler is running")
        else:
            logger.error("✗ Scheduler is NOT running!")
        
        logger.info(f"Current time: {datetime.now(self._timezone)}")
        logger.info(f"Timezone: {self._timezone}")
    
    def stop(self) -> None:
        """Stop the scheduler."""
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("Scheduler stopped")
    
    async def run_now(self) -> None:
        """Run the task immediately (for testing)."""
        if self._task_function:
            await self._task_function()
