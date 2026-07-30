ALTER TABLE print_records ADD COLUMN completion_time_accuracy TEXT NOT NULL DEFAULT 'exact'
  CHECK(completion_time_accuracy IN ('exact','estimated','unknown'));
