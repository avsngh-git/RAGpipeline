-- Claims kept by quote verification store the passage text they were checked against.
-- Claims from earlier runs keep a NULL quote.
ALTER TABLE claims ADD COLUMN quote TEXT CHECK (quote IS NULL OR length(quote) > 0);
