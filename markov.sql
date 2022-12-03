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

--a table of channel operators to be used for the !oplist commands
CREATE TABLE IF NOT EXISTS user_accounts(
	--the nick of this operator
	nick VARCHAR(256) NOT NULL PRIMARY KEY,
	
	--the bcrypted hash of this user's passphrase
	--null iff the user has not yet accepted their invitation
	pass_hash VARCHAR(256),
	
	--the list (array) of hostmasks where this user has been seen before
	--the only time this matters for authorization is when the passphrase is null,
	--in which case it is used to determine whether or not you should be allowed to sign up
	hostmasks VARCHAR(256)[]
);

--a table of channel permissions for the operators in the user_accounts table
CREATE TABLE IF NOT EXISTS user_channel_modes(
	nick VARCHAR(256) REFERENCES user_accounts(nick),
	
	--the name of the channel this user is an operator in
	channel VARCHAR(256) NOT NULL,

	--the mode in this channel that this this user is authorized for
	mode_str VARCHAR(8) NOT NULL DEFAULT 'o',

	--an operator authorization is determined by a unique combination of channel and nick
	PRIMARY KEY (channel,nick,mode_str)
);

--a table of tell queue messages
CREATE TABLE IF NOT EXISTS tell_msg(
	--when this message was stored, in ISO8601 format
	time_sent VARCHAR(64) NOT NULL,
	
	--who sent it
	sender VARCHAR(256) NOT NULL,
	
	--who is to receive it
	nick VARCHAR(256) NOT NULL,
	
	--in which channel the message should be shown
	channel VARCHAR(256) NOT NULL,
	
	--the text content of the message itself
	content VARCHAR(256) NOT NULL
);


--a table of blacklisted words and phrases
--that we don't want to generate
CREATE TABLE IF NOT EXISTS blacklist_words(
	--the channel in which this blacklist applies
	--if we ever support multiple simultaneous server connections
	--server would be stored here too
	--but for now we don't so it's not
	channel VARCHAR(256) NOT NULL,
	
	--the blacklisted word or phrase
	word_or_phrase VARCHAR(512) NOT NULL,
	
	--entries are the same iff they share both channel and word_or_phrase
	PRIMARY KEY (channel,word_or_phrase)
);


