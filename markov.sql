--this file creates the database schema for "markovdb"

--CREATE DATABASE markovdb;

--a table of state transitions
CREATE TABLE IF NOT EXISTS states(
	--the prefix (multiple words are space-delimited)
	prefix VARCHAR(512) NOT NULL,
	--the suffix (always a single word)
	suffix VARCHAR(512) NOT NULL,
	--the count, how many times this combination was seen
	count INTEGER NOT NULL DEFAULT 1,
	
	--entries are the same iff they share both prefix and suffix
	PRIMARY KEY (prefix,suffix)
);

