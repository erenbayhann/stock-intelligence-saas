from app.scheduler import ET, build_scheduler

EXPECTED_JOB_IDS = {
    "market_data_ingestion",
    "result_evaluation",
    "champion_performance_check",
    "news_ingestion_1700",
    "news_ingestion_1930",
    "news_ingestion_2200",
    "news_ingestion_0030",
    "news_ingestion_0300",
    "news_ingestion_0600",
    "news_ingestion_0845",
    "macro_ingestion",
    "fundamentals_ingestion",
    "filings_ingestion",
    "feature_generation",
    "prediction_generation",
    "news_pick_generation",
    "historical_dataset_construction",
    "weekly_training",
    "challenger_experiment",
}


def test_build_scheduler_registers_every_expected_job():
    scheduler = build_scheduler()
    job_ids = {job.id for job in scheduler.get_jobs()}
    assert job_ids == EXPECTED_JOB_IDS


def test_scheduled_jobs_run_before_the_09_30_market_open():
    # Regression guard: feature generation and prediction generation must
    # both fire, in order, before the 09:30 ET open — spec §11's feature
    # freeze depends on that ordering.
    scheduler = build_scheduler()
    jobs = {job.id: job for job in scheduler.get_jobs()}

    feature_trigger = jobs["feature_generation"].trigger
    prediction_trigger = jobs["prediction_generation"].trigger

    feature_time = (feature_trigger.fields[5].expressions[0].first, feature_trigger.fields[6].expressions[0].first)
    prediction_time = (
        prediction_trigger.fields[5].expressions[0].first,
        prediction_trigger.fields[6].expressions[0].first,
    )
    assert feature_time < prediction_time
    assert prediction_time < (9, 30)


def test_scheduler_uses_eastern_time():
    scheduler = build_scheduler()
    assert str(scheduler.timezone) == ET


def test_morning_lock_jobs_only_fire_on_weekdays():
    # A Saturday/Sunday run would lock a pick set for a day the market isn't
    # open — nothing could ever evaluate it.
    scheduler = build_scheduler()
    jobs = {job.id: job for job in scheduler.get_jobs()}

    for job_id in ("feature_generation", "prediction_generation", "news_pick_generation"):
        day_of_week = str(jobs[job_id].trigger.fields[4])
        assert day_of_week == "mon-fri", f"{job_id} runs on {day_of_week}"


def test_news_picks_lock_on_the_same_minute_as_the_ranking_prediction():
    scheduler = build_scheduler()
    jobs = {job.id: job for job in scheduler.get_jobs()}

    def hhmm(job_id):
        fields = jobs[job_id].trigger.fields
        return (fields[5].expressions[0].first, fields[6].expressions[0].first)

    assert hhmm("news_pick_generation") == hhmm("prediction_generation") == (9, 15)
