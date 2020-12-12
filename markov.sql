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

CREATE TABLE IF NOT EXISTS oplist_users(
	--the nick of this operator
	nick VARCHAR(256) NOT NULL PRIMARY KEY,
	
	--the bcrypted hash of this user's passphrase
	--null iff the user has not yet accepted their invitation
	passphrase VARCHAR(256),
	
	--the list (array) of hostmasks where this user has been seen before
	--the only time this matters for authorization is when the passphrase is null,
	--in which case it is used to determine whether or not you should be allowed to sign up
	hostmasks VARCHAR(256)[]
);

--a table of channel operators to be used for the !oplist commands
CREATE TABLE IF NOT EXISTS oplist_channels(
	nick VARCHAR(256) REFERENCES oplist_users(nick),
	
	--the name of the channel this user is an operator in
	channel VARCHAR(256) NOT NULL,

	--the mode in this channel that this this user is authorized for
	ch_mode VARCHAR(8) NOT NULL DEFAULT 'o',

	--an operator authorization is determined by a unique combination of channel and nick
	PRIMARY KEY (channel,nick,ch_mode)
);

