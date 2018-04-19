import time
import decimal
from common import generalUtils
from common.constants import gameModes
from common.constants import privileges
from common.constants import mods
from common.log import logUtils as log
from common.ripple import passwordUtils, scoreUtils
from objects import glob
from helpers import leaderboardHelper

def logUserLog(log,fileMd5,userID, gameMode):
	glob.db.execute("INSERT INTO users_logs (user, log, time, game_mode, beatmap_md5) VALUES (%s, %s, %s, %s, %s)",[userID, log, int(time.time()), gameMode, fileMd5])
	return True

def getUserStats(userID, gameMode):
	"""
	Get all user stats relative to `gameMode`

	:param userID:
	:param gameMode: game mode number
	:return: dictionary with result
	"""
	modeForDB = gameModes.getGameModeForDB(gameMode)

	# Get stats
	stats = glob.db.fetch("""SELECT
						ranked_score_{gm} AS rankedScore,
						avg_accuracy_{gm} AS accuracy,
						playcount_{gm} AS playcount,
						total_score_{gm} AS totalScore,
						pp_{gm} AS pp
						FROM users_stats WHERE id = %s LIMIT 1""".format(gm=modeForDB), [userID])

	# Get game rank
	result = glob.db.fetch("SELECT position FROM leaderboard_{} WHERE user = %s LIMIT 1".format(modeForDB), [userID])
	if result is None:
		stats["gameRank"] = 0
	else:
		stats["gameRank"] = result["position"]

	# Return stats + game rank
	return stats

def getIDSafe(_safeUsername):
	"""
	Get user ID from a safe username
	:param _safeUsername: safe username
	:return: None if the user doesn't exist, else user id
	"""
	result = glob.db.fetch("SELECT id FROM users WHERE username_safe = %s LIMIT 1", [_safeUsername])
	if result is not None:
		return result["id"]
	return None

def getID(username):
	"""
	Get username's user ID from userID redis cache (if cache hit)
	or from db (and cache it for other requests) if cache miss

	:param username: user
	:return: user id or 0 if user doesn't exist
	"""
	# Get userID from redis
	usernameSafe = safeUsername(username)
	userID = glob.redis.get("ripple:userid_cache:{}".format(usernameSafe))

	if userID is None:
		# If it's not in redis, get it from mysql
		userID = getIDSafe(usernameSafe)

		# If it's invalid, return 0
		if userID is None:
			return 0

		# Otherwise, save it in redis and return it
		glob.redis.set("ripple:userid_cache:{}".format(usernameSafe), userID, 3600)	# expires in 1 hour
		return userID

	# Return userid from redis
	return int(userID)

def getUsername(userID):
	"""
	Get userID's username

	:param userID: user id
	:return: username or None
	"""
	result = glob.db.fetch("SELECT username FROM users WHERE id = %s LIMIT 1", [userID])
	if result is None:
		return None
	return result["username"]

def getSafeUsername(userID):
	"""
	Get userID's safe username

	:param userID: user id
	:return: username or None
	"""
	result = glob.db.fetch("SELECT username_safe FROM users WHERE id = %s LIMIT 1", [userID])
	if result is None:
		return None
	return result["username_safe"]

def exists(userID):
	"""
	Check if given userID exists

	:param userID: user id to check
	:return: True if the user exists, else False
	"""
	return True if glob.db.fetch("SELECT id FROM users WHERE id = %s LIMIT 1", [userID]) is not None else False

def checkLogin(userID, password, ip=""):
	"""
	Check userID's login with specified password

	:param userID: user id
	:param password: md5 password
	:param ip: request IP (used to check active bancho sessions). Optional.
	:return: True if user id and password combination is valid, else False
	"""
	# Check cached bancho session
	banchoSession = False
	if ip != "":
		banchoSession = checkBanchoSession(userID, ip)

	# Return True if there's a bancho session for this user from that ip
	if banchoSession:
		return True

	# Otherwise, check password
	# Get password data
	passwordData = glob.db.fetch("SELECT password_md5, salt, password_version FROM users WHERE id = %s LIMIT 1", [userID])

	# Make sure the query returned something
	if passwordData is None:
		return False

	# Return valid/invalid based on the password version.
	if passwordData["password_version"] == 2:
		return passwordUtils.checkNewPassword(password, passwordData["password_md5"])
	if passwordData["password_version"] == 1:
		ok = passwordUtils.checkOldPassword(password, passwordData["salt"], passwordData["password_md5"])
		if not ok:
			return False
		newpass = passwordUtils.genBcrypt(password)
		glob.db.execute("UPDATE users SET password_md5=%s, salt='', password_version='2' WHERE id = %s LIMIT 1", [newpass, userID])

def getRequiredScoreForLevel(level):
	"""
	Return score required to reach a level

	:param level: level to reach
	:return: required score
	"""
	if level <= 100:
		if level >= 2:
			return 5000 / 3 * (4 * (level ** 3) - 3 * (level ** 2) - level) + 1.25 * (1.8 ** (level - 60))
		elif level <= 0 or level == 1:
			return 1  # Should be 0, but we get division by 0 below so set to 1
	elif level >= 101:
		return 26931190829 + 100000000000 * (level - 100)

def getLevel(totalScore):
	"""
	Return level from totalScore

	:param totalScore: total score
	:return: level
	"""
	level = 1
	while True:
		# if the level is > 8000, it's probably an endless loop. terminate it.
		if level > 8000:
			return level

		# Calculate required score
		reqScore = getRequiredScoreForLevel(level)

		# Check if this is our level
		if totalScore <= reqScore:
			# Our level, return it and break
			return level - 1
		else:
			# Not our level, calculate score for next level
			level += 1

def updateLevel(userID, gameMode=0, totalScore=0):
	"""
	Update level in DB for userID relative to gameMode

	:param userID: user id
	:param gameMode: game mode number
	:param totalScore: new total score
	:return:
	"""
	# Make sure the user exists
	# if not exists(userID):
	#	return

	# Get total score from db if not passed
	mode = scoreUtils.readableGameMode(gameMode)
	if totalScore == 0:
		totalScore = glob.db.fetch(
			"SELECT total_score_{m} as total_score FROM users_stats WHERE id = %s LIMIT 1".format(m=mode), [userID])
		if totalScore:
			totalScore = totalScore["total_score"]

	# Calculate level from totalScore
	level = getLevel(totalScore)

	# Save new level
	glob.db.execute("UPDATE users_stats SET level_{m} = %s WHERE id = %s LIMIT 1".format(m=mode), [level, userID])

def calculateAccuracy(userID, gameMode):
	"""
	Calculate accuracy value for userID relative to gameMode

	:param userID: user id
	:param gameMode: game mode number
	:return: new accuracy
	"""
	# Select what to sort by
	# Get best accuracy scores
	bestAccScores = glob.db.fetchAll(
		"SELECT accuracy FROM scores WHERE userid = %s AND play_mode = %s AND completed = 3 ORDER BY pp DESC LIMIT 500",
		[userID, gameMode])

	v = 0
	if bestAccScores is not None:
		# Calculate weighted accuracy
		totalAcc = 0
		divideTotal = 0
		k = 0
		for i in bestAccScores:
			add = int((0.95 ** k) * 100)
			totalAcc += i["accuracy"] * add
			divideTotal += add
			k += 1
		# echo "$add - $totalacc - $divideTotal\n"
		if divideTotal != 0:
			v = totalAcc / divideTotal
		else:
			v = 0
	return v

def calculatePP(userID, gameMode):
	"""
	Calculate userID's total PP for gameMode

	:param userID: user id
	:param gameMode: game mode number
	:return: total PP
	"""
	# Get best pp scores
	bestPPScores = glob.db.fetchAll(
		"SELECT pp FROM scores WHERE userid = %s AND play_mode = %s AND completed = 3 ORDER BY pp DESC LIMIT 500",
		[userID, gameMode])

	# Calculate weighted PP
	totalPP = 0
	if bestPPScores is not None:
		k = 0
		for i in bestPPScores:
			new = i["pp"] * pow(0.95, k)
			totalPP += new
			k += 1

	return round(totalPP)

def addModsBonus(x, m, pp):
	if m & mods.HIDDEN > 0:
		x *= 1.032
	if m & mods.FLASHLIGHT > 0 and pp > 100:
		x *= 3
	return x

def lengthBonusMultiplier(l):
    if (l <= 320):
        return 1
    if (l >= 30*60):
        return 30
    return (l-320)*29.0/(1800-320)+1
	
def recalcFirstPlaces(userID):
	
	c = glob.db.fetch("select * from user_first_places WHERE userid = %s",[userID])
	
	fs = glob.db.fetchAll("SELECT o.pp pp, o.mods mods,	beatmap_id, difficulty_std stars, difficulty_hr starsHR, difficulty_dt starsDT, hit_length length FROM (SELECT scores.* from scores JOIN users ON scores.userid = users.id WHERE privileges > 2 AND completed = 3 AND play_mode = 0) o LEFT JOIN (SELECT scores.* from scores JOIN users ON scores.userid = users.id WHERE privileges > 2 AND completed = 3 AND play_mode = 0) b on o.beatmap_md5 = b.beatmap_md5 AND o.pp < b.pp JOIN beatmaps ON o.beatmap_md5 = beatmaps.beatmap_md5 WHERE b.pp is NULL AND o.userid = %s AND o.play_mode = 0 AND o.completed = 3 AND o.pp > 40",[userID])

	if fs is None:
		return

	fvalue = 0		
	for f in fs:
		mod = scoreUtils.readableMods(int(f["mods"]) & 80)
		stars = f["stars"]
		if(mod == "HR" or mod == "DT"):
			if(f["stars{}".format(mod)] <= 0):
				log.error("stars <= 0 beatmap: {}".format(f["beatmap_id"]))
			else:
				stars = f["stars{}".format(mod)]
				
		cv = addModsBonus(stars,f["mods"],f["pp"]) ** 4.45 / 800
		fvalue += cv * lengthBonusMultiplier(f["length"])
	
	fvalue = round(fvalue)
	
	if c is None:
		glob.db.execute("INSERT INTO user_first_places(userid,value) VALUES(%s,%s)",[userID, fvalue])
	else:
		glob.db.execute("UPDATE user_first_places SET value = %s WHERE userID = %s",[fvalue, userID])
	
def peakRankBonus(d):
    if d > 5000:
        return 0
    if d < 10:
        return 1000.0 / d**0.5
    if d < 100:
        return 3160 / d
    return (5000**2 - d**2) / 500**2

def rankedScoreBonus(s):
    return s ** decimal.Decimal(1.0/3.6)
	
def calculateUserClanPerformance(userID):
	total_rating = 0

	# 1. Top scores
	
	bestPPScore = glob.db.fetch("SELECT max(scores.pp) pp FROM scores WHERE userid = %s AND play_mode = 0 AND completed = 3 GROUP BY userid ORDER BY pp DESC LIMIT 1",[userID])

	if bestPPScore is not None:
		total_rating += bestPPScore["pp"] ** 2 / 400.0
	
	# 2. Top 1 places
	
	topPlaces = glob.db.fetch("SELECT value FROM user_first_places WHERE userid = %s",[userID])
	
	if topPlaces is None:
		recalcFirstPlaces(userID)
		topPlaces = glob.db.fetch("SELECT value FROM user_first_places WHERE userid = %s",[userID])
	
	if topPlaces is not None:
		total_rating += int(topPlaces["value"])
		
	
	# 3. peak rank
	
	peakRank = glob.db.fetch("select peak_rank from users_peak_rank WHERE userid = %s",[userID])
	
	if peakRank is not None:
		total_rating += round(peakRankBonus(peakRank["peak_rank"]))
	
	return total_rating
	
def calculateClanRating(clanID, gameMode):
	"""
	Calculate clan rating

	:param clanID: clan id
	:param gameMode: game mode number
	:return: clan rating
	"""
	if(gameMode != 0):
		return
	total_rating = 0
	
	# 1. Sum of user performances
	ps = glob.db.fetch("SELECT SUM(performance) performance FROM clan_users WHERE clanid = %s",[clanID])
	if ps is not None:
		total_rating += ps["performance"]
	
	# 2. Medals
	medals = glob.db.fetch("SELECT SUM(points) points  FROM clan_badges JOIN badges  WHERE clan_badges.clan = %s",[clanID])

	if medals is not None:
		if total_rating is not None and medals["points"] is not None:
			total_rating += medals["points"]
	
	#3. Total users ranked score
	rs = glob.db.fetch("select SUM(users_stats.ranked_score_std) ranked_score_std from users_stats JOIN clan_users ON clan_users.userid = users_stats.id where clanid = %s GROUP BY clanid",[clanID])
	if rs is not None:
		total_rating += rankedScoreBonus(rs["ranked_score_std"])
	
	#4. Map siege points
	siege_points = glob.db.fetch("SELECT points FROM clan_siege_points WHERE clanid = %s",[clanID])
	
	if siege_points is not None:
		total_rating += decimal.Decimal(siege_points["points"])
	
	return total_rating
	
def updateAccuracy(userID, gameMode):
	"""
	Update accuracy value for userID relative to gameMode in DB

	:param userID: user id
	:param gameMode: gameMode number
	:return:
	"""
	newAcc = calculateAccuracy(userID, gameMode)
	mode = scoreUtils.readableGameMode(gameMode)
	glob.db.execute("UPDATE users_stats SET avg_accuracy_{m} = %s WHERE id = %s LIMIT 1".format(m=mode),
					[newAcc, userID])

def updatePP(userID, gameMode):
	"""
	Update userID's pp with new value

	:param userID: user id
	:param gameMode: game mode number
	"""
	# Make sure the user exists
	# if not exists(userID):
	#	return

	# Get new total PP and update db
	newPP = calculatePP(userID, gameMode)
	mode = scoreUtils.readableGameMode(gameMode)
	glob.db.execute("UPDATE users_stats SET pp_{}=%s WHERE id = %s LIMIT 1".format(mode), [newPP, userID])

def getClanID(userID):
	d = glob.db.fetch("SELECT clanid from clan_users WHERE userid = %s LIMIT 1", [userID])
	if d is not None:
		return d["clanid"]
	else:
		return None

def updateUserClanPerformance(userID):
	clanID = getClanID(userID)
	
	if clanID is not None:
		newUserPerformance = calculateUserClanPerformance(userID)
		glob.db.execute("UPDATE clan_users SET performance = %s WHERE userid = %s LIMIT 1", [newUserPerformance, userID])

def updateEmptyUserClanPerformances(clanID):
	users = glob.db.fetchAll("SELECT * from clan_users WHERE clanid = %s",[clanID])
	if users is not None:
		for user in users:
			topPlaces = glob.db.fetch("SELECT * from user_first_places WHERE userid = %s",[user["userid"]])
			if topPlaces is None:
				recalcFirstPlaces(user["userid"])
		
			if (user["performance"] < 1):
				updateUserClanPerformance(user["userid"])
			
		
def updateClanRating(userID, gameMode):
	"""
	Update userID's pp with new value

	:param userID: user id
	:param gameMode: game mode number
	"""

	gameMode = 0 #STD for now
	# Get new clan rating update db
	clanID = getClanID(userID)
	
	if clanID is not None:
		updateEmptyUserClanPerformances(clanID)
		
		newClanRating = calculateClanRating(clanID,gameMode)
		glob.db.execute("UPDATE clans SET performance = %s WHERE id = %s LIMIT 1", [newClanRating, clanID])
		leaderboardHelper.updateClans(clanID, newClanRating)

	
def updateStats(userID, __score):
	"""
	Update stats (playcount, total score, ranked score, level bla bla)
	with data relative to a score object

	:param userID:
	:param __score: score object
	"""

	# Make sure the user exists
	if not exists(userID):
		log.warning("User {} doesn't exist.".format(userID))
		return

	# Get gamemode for db
	mode = scoreUtils.readableGameMode(__score.gameMode)

	# Update total score and playcount
	glob.db.execute(
		"UPDATE users_stats SET total_score_{m}=total_score_{m}+%s, playcount_{m}=playcount_{m}+1 WHERE id = %s LIMIT 1".format(
			m=mode), [__score.score, userID])

	# Calculate new level and update it
	updateLevel(userID, __score.gameMode)

	# Update level, accuracy and ranked score only if we have passed the song
	if __score.passed:
		# Update ranked score
		glob.db.execute(
			"UPDATE users_stats SET ranked_score_{m}=ranked_score_{m}+%s WHERE id = %s LIMIT 1".format(m=mode),
			[__score.rankedScoreIncrease, userID])

		# Update accuracy
		updateAccuracy(userID, __score.gameMode)

		# Update pp
		updatePP(userID, __score.gameMode)
		
		# Update clan rating
		updateUserClanPerformance(userID)
		
		updateClanRating(userID, __score.gameMode)

def updateLatestActivity(userID):
	"""
	Update userID's latest activity to current UNIX time

	:param userID: user id
	:return:
	"""
	glob.db.execute("UPDATE users SET latest_activity = %s WHERE id = %s LIMIT 1", [int(time.time()), userID])

def getRankedScore(userID, gameMode):
	"""
	Get userID's ranked score relative to gameMode

	:param userID: user id
	:param gameMode: game mode number
	:return: ranked score
	"""
	mode = scoreUtils.readableGameMode(gameMode)
	result = glob.db.fetch("SELECT ranked_score_{} FROM users_stats WHERE id = %s LIMIT 1".format(mode), [userID])
	if result is not None:
		return result["ranked_score_{}".format(mode)]
	else:
		return 0

def getPP(userID, gameMode):
	"""
	Get userID's PP relative to gameMode

	:param userID: user id
	:param gameMode: game mode number
	:return: pp
	"""

	mode = scoreUtils.readableGameMode(gameMode)
	result = glob.db.fetch("SELECT pp_{} FROM users_stats WHERE id = %s LIMIT 1".format(mode), [userID])
	if result is not None:
		return result["pp_{}".format(mode)]
	else:
		return 0

def incrementReplaysWatched(scoreID, userID, gameMode):
	"""
	Increment userID's replays watched by others relative to gameMode

	:param userID: user id
	:param gameMode: game mode number
	:return:
	"""
	mode = scoreUtils.readableGameMode(gameMode)
	glob.db.execute(
		"UPDATE scores SET watched = watched + 1 WHERE id = %s LIMIT 1", [scoreID])
	glob.db.execute(
		"UPDATE users_stats SET replays_watched_{mode}=replays_watched_{mode}+1 WHERE id = %s LIMIT 1".format(
			mode=mode), [userID])

def getAqn(userID):
	"""
	Check if AQN folder was detected for userID

	:param userID: user
	:return: True if hax, False if legit
	"""
	result = glob.db.fetch("SELECT aqn FROM users WHERE id = %s LIMIT 1", [userID])
	if result is not None:
		return True if int(result["aqn"]) == 1 else False
	else:
		return False

def setAqn(userID, value=1):
	"""
	Set AQN folder status for userID

	:param userID: user
	:param value: new aqn value, default = 1
	:return:
	"""
	glob.db.fetch("UPDATE users SET aqn = %s WHERE id = %s LIMIT 1", [value, userID])

def IPLog(userID, ip):
	"""
	Log user IP

	:param userID: user id
	:param ip: IP address
	:return:
	"""
	if ((ip != "127.0.0.1") & (ip != "::1")):
		glob.db.execute("""INSERT INTO ip_user (userid, ip, occurencies) VALUES (%s, %s, '1')
						ON DUPLICATE KEY UPDATE occurencies = occurencies + 1""", [userID, ip])

def checkBanchoSession(userID, ip=""):
	"""
	Return True if there is a bancho session for `userID` from `ip`
	If `ip` is an empty string, check if there's a bancho session for that user, from any IP.

	:param userID: user id
	:param ip: ip address. Optional. Default: empty string
	:return: True if there's an active bancho session, else False
	"""
	if ip != "":
		return glob.redis.sismember("peppy:sessions:{}".format(userID), ip)
	else:
		return glob.redis.exists("peppy:sessions:{}".format(userID))

def is2FAEnabled(userID):
	"""
	Returns True if 2FA/Google auth 2FA is enable for `userID`

	:userID: user ID
	:return: True if 2fa is enabled, else False
	"""
	result = glob.db.fetch("SELECT IFNULL((SELECT 1 FROM 2fa_telegram WHERE userid = %(userid)s LIMIT 1), 0) | IFNULL((SELECT 2 FROM 2fa_totp WHERE userid = %(userid)s AND enabled = 1 LIMIT 1), 0) AS x", {
		"userid": userID
	})
	if result is None:
		return False
	return True if result["x"] > 0 else False

def check2FA(userID, ip):
	"""
	Returns True if this IP is untrusted.
	Returns always False if 2fa is not enabled on `userID`

	:param userID: user id
	:param ip: IP address
	:return: True if untrusted, False if trusted or 2fa is disabled.
	"""
	if not is2FAEnabled(userID):
		return False
	result = glob.db.fetch("SELECT id FROM ip_user WHERE userid = %s AND ip = %s", [userID, ip])
	return True if result is None else False

def isAllowed(userID):
	"""
	Check if userID is not banned or restricted

	:param userID: user id
	:return: True if not banned or restricted, otherwise false.
	"""
	result = glob.db.fetch("SELECT privileges FROM users WHERE id = %s LIMIT 1", [userID])
	if result is not None:
		return (result["privileges"] & privileges.USER_NORMAL) and (result["privileges"] & privileges.USER_PUBLIC)
	else:
		return False

def isRestricted(userID):
	"""
	Check if userID is restricted

	:param userID: user id
	:return: True if not restricted, otherwise false.
	"""
	result = glob.db.fetch("SELECT privileges FROM users WHERE id = %s LIMIT 1", [userID])
	if result is not None:
		return (result["privileges"] & privileges.USER_NORMAL) and not (result["privileges"] & privileges.USER_PUBLIC)
	else:
		return False

def isBanned(userID):
	"""
	Check if userID is banned

	:param userID: user id
	:return: True if not banned, otherwise false.
	"""
	result = glob.db.fetch("SELECT privileges FROM users WHERE id = %s LIMIT 1", [userID])
	if result is not None:
		return not (result["privileges"] & 3 > 0)
	else:
		return True

def isLocked(userID):
	"""
	Check if userID is locked

	:param userID: user id
	:return: True if not locked, otherwise false.
	"""
	result = glob.db.fetch("SELECT privileges FROM users WHERE id = %s LIMIT 1", [userID])
	if result is not None:
		return (
		(result["privileges"] & privileges.USER_PUBLIC > 0) and (result["privileges"] & privileges.USER_NORMAL == 0))
	else:
		return True

def ban(userID):
	"""
	Ban userID

	:param userID: user id
	:return:
	"""
	banDateTime = int(time.time())
	glob.db.execute("UPDATE users SET privileges = privileges & %s, ban_datetime = %s WHERE id = %s LIMIT 1",
					[~(privileges.USER_NORMAL | privileges.USER_PUBLIC), banDateTime, userID])
	glob.redis.publish("peppy:ban", userID)

def unban(userID):
	"""
	Unban userID

	:param userID: user id
	:return:
	"""
	glob.db.execute("UPDATE users SET privileges = privileges | %s, ban_datetime = 0 WHERE id = %s LIMIT 1",
					[(privileges.USER_NORMAL | privileges.USER_PUBLIC), userID])
	glob.redis.publish("peppy:ban", userID)

def restrict(userID):
	"""
	Restruct userID

	:param userID: user id
	:return:
	"""
	if not isRestricted(userID):
		banDateTime = int(time.time())
		glob.db.execute("UPDATE users SET privileges = privileges & %s, ban_datetime = %s WHERE id = %s LIMIT 1",
						[~privileges.USER_PUBLIC, banDateTime, userID])
		glob.redis.publish("peppy:ban", userID)

def unrestrict(userID):
	"""
	Unrestrict userID.
	Same as unban().

	:param userID: user id
	:return:
	"""
	unban(userID)

def appendNotes(userID, notes, addNl=True, trackDate=True):
	"""
	Append `notes` to `userID`'s "notes for CM"

	:param userID: user id
	:param notes: text to append
	:param addNl: if True, prepend \n to notes. Default: True.
	:param trackDate: if True, prepend date and hour to the note. Default: True.
	:return:
	"""
	if trackDate:
		notes = "[{}] {}".format(generalUtils.getTimestamp(), notes)
	if addNl:
		notes = "\n{}".format(notes)
	glob.db.execute("UPDATE users SET notes=CONCAT(COALESCE(notes, ''),%s) WHERE id = %s LIMIT 1", [notes, userID])

def getPrivileges(userID):
	"""
	Return `userID`'s privileges

	:param userID: user id
	:return: privileges number
	"""
	result = glob.db.fetch("SELECT privileges FROM users WHERE id = %s LIMIT 1", [userID])
	if result is not None:
		return result["privileges"]
	else:
		return 0

def getSilenceEnd(userID):
	"""
	Get userID's **ABSOLUTE** silence end UNIX time
	Remember to subtract time.time() if you want to get the actual silence time

	:param userID: user id
	:return: UNIX time
	"""
	return glob.db.fetch("SELECT silence_end FROM users WHERE id = %s LIMIT 1", [userID])["silence_end"]

def silence(userID, seconds, silenceReason, author = 999):
	"""
	Silence someone

	:param userID: user id
	:param seconds: silence length in seconds
	:param silenceReason: silence reason shown on website
	:param author: userID of who silenced the user. Default: 999
	:return:
	"""
	# db qurey
	silenceEndTime = int(time.time())+seconds
	glob.db.execute("UPDATE users SET silence_end = %s, silence_reason = %s WHERE id = %s LIMIT 1", [silenceEndTime, silenceReason, userID])

	# Log
	targetUsername = getUsername(userID)
	# TODO: exists check im drunk rn i need to sleep (stampa piede ubriaco confirmed)
	if seconds > 0:
		log.rap(author, "has silenced {} for {} seconds for the following reason: \"{}\"".format(targetUsername, seconds, silenceReason), True)
	else:
		log.rap(author, "has removed {}'s silence".format(targetUsername), True)

def getTotalScore(userID, gameMode):
	"""
	Get `userID`'s total score relative to `gameMode`

	:param userID: user id
	:param gameMode: game mode number
	:return: total score
	"""
	modeForDB = gameModes.getGameModeForDB(gameMode)
	return glob.db.fetch("SELECT total_score_"+modeForDB+" FROM users_stats WHERE id = %s LIMIT 1", [userID])["total_score_"+modeForDB]

def getAccuracy(userID, gameMode):
	"""
	Get `userID`'s average accuracy relative to `gameMode`

	:param userID: user id
	:param gameMode: game mode number
	:return: accuracy
	"""
	modeForDB = gameModes.getGameModeForDB(gameMode)
	return glob.db.fetch("SELECT avg_accuracy_"+modeForDB+" FROM users_stats WHERE id = %s LIMIT 1", [userID])["avg_accuracy_"+modeForDB]

def getGameRank(userID, gameMode):
	"""
	Get `userID`'s **in-game rank** (eg: #1337) relative to gameMode

	:param userID: user id
	:param gameMode: game mode number
	:return: game rank
	"""
	modeForDB = gameModes.getGameModeForDB(gameMode)
	result = glob.db.fetch("SELECT position FROM leaderboard_"+modeForDB+" WHERE user = %s LIMIT 1", [userID])
	if result is None:
		return 0
	else:
		return result["position"]

def getPlaycount(userID, gameMode):
	"""
	Get `userID`'s playcount relative to `gameMode`

	:param userID: user id
	:param gameMode: game mode number
	:return: playcount
	"""
	modeForDB = gameModes.getGameModeForDB(gameMode)
	return glob.db.fetch("SELECT playcount_"+modeForDB+" FROM users_stats WHERE id = %s LIMIT 1", [userID])["playcount_"+modeForDB]

def getFriendList(userID):
	"""
	Get `userID`'s friendlist

	:param userID: user id
	:return: list with friends userIDs. [0] if no friends.
	"""
	# Get friends from db
	friends = glob.db.fetchAll("SELECT user2 FROM users_relationships WHERE user1 = %s", [userID])

	if friends is None or len(friends) == 0:
		# We have no friends, return 0 list
		return [0]
	else:
		# Get only friends
		friends = [i["user2"] for i in friends]

		# Return friend IDs
		return friends

def addFriend(userID, friendID):
	"""
	Add `friendID` to `userID`'s friend list

	:param userID: user id
	:param friendID: new friend
	:return:
	"""
	# Make sure we aren't adding us to our friends
	if userID == friendID:
		return

	# check user isn't already a friend of ours
	if glob.db.fetch("SELECT id FROM users_relationships WHERE user1 = %s AND user2 = %s LIMIT 1", [userID, friendID]) is not None:
		return

	# Set new value
	glob.db.execute("INSERT INTO users_relationships (user1, user2) VALUES (%s, %s)", [userID, friendID])

def removeFriend(userID, friendID):
	"""
	Remove `friendID` from `userID`'s friend list

	:param userID: user id
	:param friendID: old friend
	:return:
	"""
	# Delete user relationship. We don't need to check if the relationship was there, because who gives a shit,
	# if they were not friends and they don't want to be anymore, be it. ¯\_(ツ)_/¯
	# TODO: LIMIT 1
	glob.db.execute("DELETE FROM users_relationships WHERE user1 = %s AND user2 = %s", [userID, friendID])


def getCountry(userID):
	"""
	Get `userID`'s country **(two letters)**.

	:param userID: user id
	:return: country code (two letters)
	"""
	return glob.db.fetch("SELECT country FROM users_stats WHERE id = %s LIMIT 1", [userID])["country"]

def setCountry(userID, country):
	"""
	Set userID's country

	:param userID: user id
	:param country: country letters
	:return:
	"""
	glob.db.execute("UPDATE users_stats SET country = %s WHERE id = %s LIMIT 1", [country, userID])

def logIP(userID, ip):
	"""
	User IP log
	USED FOR MULTIACCOUNT DETECTION

	:param userID: user id
	:param ip: IP address
	:return:
	"""
	glob.db.execute("""INSERT INTO ip_user (userid, ip, occurencies) VALUES (%s, %s, 1)
						ON DUPLICATE KEY UPDATE occurencies = occurencies + 1""", [userID, ip])

def saveBanchoSession(userID, ip):
	"""
	Save userid and ip of this token in redis
	Used to cache logins on LETS requests

	:param userID: user ID
	:param ip: IP address
	:return:
	"""
	glob.redis.sadd("peppy:sessions:{}".format(userID), ip)

def deleteBanchoSessions(userID, ip):
	"""
	Delete this bancho session from redis

	:param userID: user id
	:param ip: IP address
	:return:
	"""
	glob.redis.srem("peppy:sessions:{}".format(userID), ip)

def setPrivileges(userID, priv):
	"""
	Set userID's privileges in db

	:param userID: user id
	:param priv: privileges number
	:return:
	"""
	glob.db.execute("UPDATE users SET privileges = %s WHERE id = %s LIMIT 1", [priv, userID])

def isInPrivilegeGroup(userID, groupName):
	"""
	Check if `userID` is in a privilege group.
	Donor privilege is ignored while checking for groups.

	:param userID: user id
	:param groupName: privilege group name
	:return: True if `userID` is in `groupName`, else False
	"""
	groupPrivileges = glob.db.fetch("SELECT privileges FROM privileges_groups WHERE name = %s LIMIT 1", [groupName])
	if groupPrivileges is None:
		return False
	groupPrivileges = groupPrivileges["privileges"]
	userToken = glob.tokens.getTokenFromUserID(userID)
	if userToken is not None:
		userPrivileges = userToken.privileges
	else:
		userPrivileges = getPrivileges(userID)
	return (userPrivileges == groupPrivileges) or (userPrivileges == (groupPrivileges | privileges.USER_DONOR))


def logHardware(userID, hashes, activation = False):
	"""
	Hardware log
	USED FOR MULTIACCOUNT DETECTION


	:param userID: user id
	:param hashes:	Peppy's botnet (client data) structure (new line = "|", already split)
					[0] osu! version
					[1] plain mac addressed, separated by "."
					[2] mac addresses hash set
					[3] unique ID
					[4] disk ID
	:param activation: if True, set this hash as used for activation. Default: False.
	:return: True if hw is not banned, otherwise false
	"""
	# Make sure the strings are not empty
	for i in hashes[2:5]:
		if i == "":
			log.warning("Invalid hash set ({}) for user {} in HWID check".format(hashes, userID), "bunk")
			return False

	# Run some HWID checks on that user if he is not restricted
	if not isRestricted(userID):
		# Get username
		username = getUsername(userID)

		# Get the list of banned or restricted users that have logged in from this or similar HWID hash set
		if hashes[2] == "b4ec3c4334a0249dae95c284ec5983df":
			# Running under wine, check by unique id
			log.debug("Logging Linux/Mac hardware")
			banned = glob.db.fetchAll("""SELECT users.id as userid, hw_user.occurencies, users.username FROM hw_user
				LEFT JOIN users ON users.id = hw_user.userid
				WHERE hw_user.userid != %(userid)s
				AND hw_user.unique_id = %(uid)s
				AND (users.privileges & 3 != 3)""", {
					"userid": userID,
					"uid": hashes[3],
				})
		else:
			# Running under windows, do all checks
			log.debug("Logging Windows hardware")
			banned = glob.db.fetchAll("""SELECT users.id as userid, hw_user.occurencies, users.username FROM hw_user
				LEFT JOIN users ON users.id = hw_user.userid
				WHERE hw_user.userid != %(userid)s
				AND hw_user.unique_id = %(uid)s
				AND hw_user.disk_id = %(diskid)s
				AND (users.privileges & 3 != 3)""", {
					"userid": userID,
					"mac": hashes[2],
					"uid": hashes[3],
					"diskid": hashes[4],
				})

		for i in banned:
			# Get the total numbers of logins
			total = glob.db.fetch("SELECT COUNT(*) AS count FROM hw_user WHERE userid = %s LIMIT 1", [userID])
			# and make sure it is valid
			if total is None:
				continue
			total = total["count"]

			# Calculate 10% of total
			perc = (total*10)/100

			if i["occurencies"] >= perc:
				# If the banned user has logged in more than 10% of the times from this user, restrict this user
				restrict(userID)
				appendNotes(userID, "Logged in from HWID ({hwid}) used more than 10% from user {banned} ({bannedUserID}), who is banned/restricted.".format(
					hwid=hashes[2:5],
					banned=i["username"],
					bannedUserID=i["userid"]
				))
				log.warning("**{user}** ({userID}) has been restricted because he has logged in from HWID _({hwid})_ used more than 10% from banned/restricted user **{banned}** ({bannedUserID}), **possible multiaccount**.".format(
					user=username,
					userID=userID,
					hwid=hashes[2:5],
					banned=i["username"],
					bannedUserID=i["userid"]
				), "cm")

	# Update hash set occurencies
	glob.db.execute("""
				INSERT INTO hw_user (id, userid, mac, unique_id, disk_id, occurencies) VALUES (NULL, %s, %s, %s, %s, 1)
				ON DUPLICATE KEY UPDATE occurencies = occurencies + 1
				""", [userID, hashes[2], hashes[3], hashes[4]])

	# Optionally, set this hash as 'used for activation'
	if activation:
		glob.db.execute("UPDATE hw_user SET activated = 1 WHERE userid = %s AND mac = %s AND unique_id = %s AND disk_id = %s", [userID, hashes[2], hashes[3], hashes[4]])

	# Access granted, abbiamo impiegato 3 giorni
	# We grant access even in case of login from banned HWID
	# because we call restrict() above so there's no need to deny the access.
	return True


def resetPendingFlag(userID, success=True):
	"""
	Remove pending flag from an user.

	:param userID: user id
	:param success: if True, set USER_PUBLIC and USER_NORMAL flags too
	"""
	glob.db.execute("UPDATE users SET privileges = privileges & %s WHERE id = %s LIMIT 1", [~privileges.USER_PENDING_VERIFICATION, userID])
	if success:
		glob.db.execute("UPDATE users SET privileges = privileges | %s WHERE id = %s LIMIT 1", [(privileges.USER_PUBLIC | privileges.USER_NORMAL), userID])

def verifyUser(userID, hashes):
	"""
	Activate `userID`'s account.

	:param userID: user id
	:param hashes: 	Peppy's botnet (client data) structure (new line = "|", already split)
					[0] osu! version
					[1] plain mac addressed, separated by "."
					[2] mac addresses hash set
					[3] unique ID
					[4] disk ID
	:return: True if verified successfully, else False (multiaccount)
	"""
	# Check for valid hash set
	for i in hashes[2:5]:
		if i == "":
			log.warning("Invalid hash set ({}) for user {} while verifying the account".format(str(hashes), userID), "bunk")
			return False

	# Get username
	username = getUsername(userID)

	# Make sure there are no other accounts activated with this exact mac/unique id/hwid
	if hashes[2] == "b4ec3c4334a0249dae95c284ec5983df" or hashes[4] == "ffae06fb022871fe9beb58b005c5e21d":
		# Running under wine, check only by uniqueid
		log.info("{user} ({userID}) ha triggerato Sannino:\n**Full data:** {hashes}\n**Usual wine mac address hash:** b4ec3c4334a0249dae95c284ec5983df\n**Usual wine disk id:** ffae06fb022871fe9beb58b005c5e21d".format(user=username, userID=userID, hashes=hashes), "bunker")
		log.debug("Veryfing with Linux/Mac hardware")
		match = glob.db.fetchAll("SELECT userid FROM hw_user WHERE unique_id = %(uid)s AND userid != %(userid)s AND activated = 1 LIMIT 1", {
			"uid": hashes[3],
			"userid": userID
		})
	else:
		# Running under windows, full check
		log.debug("Veryfing with Windows hardware")
		match = glob.db.fetchAll("SELECT userid FROM hw_user WHERE mac = %(mac)s AND unique_id = %(uid)s AND disk_id = %(diskid)s AND userid != %(userid)s AND activated = 1 LIMIT 1", {
			"mac": hashes[2],
			"uid": hashes[3],
			"diskid": hashes[4],
			"userid": userID
		})

	if match:
		# This is a multiaccount, restrict other account and ban this account

		# Get original userID and username (lowest ID)
		originalUserID = match[0]["userid"]
		originalUsername = getUsername(originalUserID)

		# Ban this user and append notes
		ban(userID)	# this removes the USER_PENDING_VERIFICATION flag too
		appendNotes(userID, "{}'s multiaccount ({}), found HWID match while verifying account ({})".format(originalUsername, originalUserID, hashes[2:5]))
		appendNotes(originalUserID, "Has created multiaccount {} ({})".format(username, userID))

		# Restrict the original
		restrict(originalUserID)

		# Discord message
		log.warning("User **{originalUsername}** ({originalUserID}) has been restricted because he has created multiaccount **{username}** ({userID}). The multiaccount has been banned.".format(
			originalUsername=originalUsername,
			originalUserID=originalUserID,
			username=username,
			userID=userID
		), "cm")

		# Disallow login
		return False
	else:
		# No matches found, set USER_PUBLIC and USER_NORMAL flags and reset USER_PENDING_VERIFICATION flag
		resetPendingFlag(userID)
		#log.info("User **{}** ({}) has verified his account with hash set _{}_".format(username, userID, hashes[2:5]), "cm")

		# Allow login
		return True

def hasVerifiedHardware(userID):
	"""
	Checks if `userID` has activated his account through HWID

	:param userID: user id
	:return: True if hwid activation data is in db, otherwise False
	"""
	data = glob.db.fetch("SELECT id FROM hw_user WHERE userid = %s AND activated = 1 LIMIT 1", [userID])
	if data is not None:
		return True
	return False

def getDonorExpire(userID):
	"""
	Return `userID`'s donor expiration UNIX timestamp

	:param userID: user id
	:return: donor expiration UNIX timestamp
	"""
	data = glob.db.fetch("SELECT donor_expire FROM users WHERE id = %s LIMIT 1", [userID])
	if data is not None:
		return data["donor_expire"]
	return 0


class invalidUsernameError(Exception):
	pass

class usernameAlreadyInUseError(Exception):
	pass

def safeUsername(username):
	"""
	Return `username`'s safe username
	(all lowercase and underscores instead of spaces)

	:param username: unsafe username
	:return: safe username
	"""
	return username.lower().strip().replace(" ", "_")

def changeUsername(userID=0, oldUsername="", newUsername=""):
	"""
	Change `userID`'s username to `newUsername` in database

	:param userID: user id. Required only if `oldUsername` is not passed.
	:param oldUsername: username. Required only if `userID` is not passed.
	:param newUsername: new username. Can't contain spaces and underscores at the same time.
	:raise: invalidUsernameError(), usernameAlreadyInUseError()
	:return:
	"""
	# Make sure new username doesn't have mixed spaces and underscores
	if " " in newUsername and "_" in newUsername:
		raise invalidUsernameError()

	# Get safe username
	newUsernameSafe = safeUsername(newUsername)

	# Make sure this username is not already in use
	if getIDSafe(newUsernameSafe) is not None:
		raise usernameAlreadyInUseError()

	# Get userID or oldUsername
	if userID == 0:
		userID = getID(oldUsername)
	else:
		oldUsername = getUsername(userID)

	# Change username
	glob.db.execute("UPDATE users SET username = %s, username_safe = %s WHERE id = %s LIMIT 1", [newUsername, newUsernameSafe, userID])
	glob.db.execute("UPDATE users_stats SET username = %s WHERE id = %s LIMIT 1", [newUsername, userID])

	# Empty redis username cache
	# TODO: Le pipe woo woo
	glob.redis.delete("ripple:userid_cache:{}".format(safeUsername(oldUsername)))
	glob.redis.delete("ripple:change_username_pending:{}".format(userID))
