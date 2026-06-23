# u115椋庢帶鍙傛暟

杩欐槸涓€涓?MoviePilot 鎻掍欢锛岀敤浜庡湪杩愯鏃朵负 `u115` 瀛樺偍娉ㄥ叆鏇翠繚瀹堢殑闄愭祦鍙傛暟锛岄伩鍏嶆瘡娆″崌绾?MP2 瀹瑰櫒鍚庡張瑕佹墜宸ヤ慨鏀?`u115.py`銆?
褰撳墠鐗堟湰锛歚0.1.15`

## 褰撳墠鐗堟湰鑳藉姏

- 鎸佷箙鍖栨櫘閫氭帴鍙?QPS
- 鎸佷箙鍖栦笅杞芥帴鍙?QPS
- 鎸佷箙鍖?`limit_sleep_seconds`
- 鏀寔灏忔椂杞槇鍊?- 鏀寔杈惧埌杞槇鍊煎悗涓诲姩鍐峰嵈
- 鏀寔椋庢帶鍐峰嵈缁撴潫鍚庤嚜鍔ㄩ噸璇?MP 濯掍綋鏁寸悊澶辫触鍘嗗彶
- 鏀寔鍦ㄩ噸璇曟棩蹇椾腑鏄剧ず璇嗗埆鍒扮殑澶辫触浠诲姟鍚嶃€佽烦杩囦换鍔″悕鍜岃烦杩囧師鍥?- 鏀寔鍦ㄧ姸鎬侀〉鏄剧ず澶辫触鏁寸悊閲嶈瘯杩涘害銆佸綋鍓嶄换鍔″拰 MP 鏁寸悊鎺ュ彛鎻愪氦缁撴灉
- 鏀寔鍦ㄧ姸鎬侀〉棣栧睆鏄剧ず褰撳墠鎬荤姸鎬侊細姝ｅ父銆侀鎺т腑銆佸紓甯搞€佺瓑寰呮壂鎻忔垨鏁寸悊鎵ц涓?- 鏀寔鍚屾绛夊緟 MP 鏁寸悊缁撴灉锛屽苟澶嶆煡鏁寸悊鍘嗗彶锛岄伩鍏嶆妸鍚庡彴鍏ラ槦璇垽涓烘暣鐞嗘垚鍔?- 鏀寔璇嗗埆婧愭枃浠朵笉瀛樺湪銆佹病鏈夊彲鏁寸悊濯掍綋鏂囦欢绛変笉鍙嚜鍔ㄤ慨澶嶇殑澶辫触鍘熷洜
- 鏀寔璇嗗埆 MoviePilot 鍐呯疆 `U115Pan._limit_until` 鍐峰嵈绐楀彛锛岄伩鍏?MP 鍐呴儴 sleep 鍚庢彃浠舵紡鎺夐噸璇曡皟搴?- 鏀寔鎻掍欢鍚姩鍚庢墽琛屼竴娆″け璐ユ暣鐞嗚ˉ鍋挎壂鎻忥紝閬垮厤瀹夎鏂扮増鏈椂鍐峰嵈宸茬粡缁撴潫鑰岄敊杩囬噸璇曡皟搴?- 鎻掍欢鍚敤鍚庤嚜鍔ㄤ负鏂板缓鐨?`U115Pan` 瀹炰緥娉ㄥ叆鍙傛暟
- 灏濊瘯涓哄綋鍓嶅凡瀛樺湪鐨?`U115Pan` 瀹炰緥鐑洿鏂板弬鏁?
## 鎺ㄨ崘榛樿鍊?
- `api_qps = 1`
- `download_qps = 1`
- `limit_sleep_seconds = 3600`
- `hourly_soft_limit = 60`
- `hourly_soft_cooldown = 1200`
- `retry_failed_after_cooldown = true`
- `retry_failed_on_startup = true`
- `retry_failed_delay_seconds = 60`
- `retry_failed_max_count = 1`

## v0.1.14 补整理策略

- 单条失败历史改为 24 小时滚动窗口内最多重试 3 次，不再累计 3 次后永久跳过。
- 每条失败历史保存 `attempt_timestamps`、`last_attempt_ts`、`next_retry_after`、`success`、`message`、`manual_required`。
- 达到 24 小时窗口上限时显示“等待冷却后重试”，跳过不记为全局异常。
- 补整理前检查最近 1 小时请求安全余量，接近 `hourly_soft_limit` 时延后重试。
- 默认每轮只补 1 条，避免风控刚结束时集中触发请求。
- 优先使用 MoviePilot 原生 `TransferChain.redo_transfer_history(history_id)`，不可用时兼容回退 `manual_transfer`。
- 成功判定会复查同源路径、目标路径、`download_hash`、`tmdbid + season + episode` 的成功历史；确认目标已存在时也会视为已处理。
- `manual_required` 仅在源文件缺失、记录损坏或连续多个周期无法处理时设置。

## v0.1.15 多集种子修复

- 修复多集种子中同 `download_hash` 任意一集成功就误判当前失败集已成功的问题。
- `download_hash` 现在只作为候选范围，必须同时匹配 `tmdbid`、`seasons`、`episodes` 才能确认成功。
- 旧版误写的 `success=true` 会在下一轮扫描时重新复查；如果没有同季同集成功记录，会自动回到滚动重试队列。

## 鍙傛暟璇存槑

- `api_qps`锛氭櫘閫氭帴鍙ｆ瘡绉掕姹傛暟锛屽缓璁繚鎸?`1`
- `download_qps`锛氫笅杞芥帴鍙ｆ瘡绉掕姹傛暟锛岄粯璁?`1`
- `limit_sleep_seconds`锛?15 鏄庣‘杩斿洖璁块棶涓婇檺鍚庣殑鏈湴鍐峰嵈绉掓暟
- `hourly_soft_limit`锛氭彃浠朵晶鑷畾涔夌殑 1 灏忔椂璇锋眰杞槇鍊硷紝璁句负 `0` 琛ㄧず鍏抽棴
- `hourly_soft_cooldown`锛氳揪鍒拌蒋闃堝€煎悗鐨勪富鍔ㄥ喎鍗寸鏁帮紝璁句负 `0` 琛ㄧず鍙褰曚笉鏆傚仠
- `retry_failed_after_cooldown`锛氶鎺у喎鍗寸粨鏉熷悗鏄惁鑷姩鏌ユ壘 MP 濯掍綋鏁寸悊澶辫触鍘嗗彶骞堕噸璇?- `retry_failed_on_startup`锛氭彃浠跺惎鍔ㄥ悗鏄惁琛ュ伩鎵弿涓€娆″け璐ユ暣鐞嗗巻鍙诧紝閫傚悎澶勭悊瀹夎鏂扮増鏈椂鍐峰嵈宸茬粡缁撴潫鐨勫満鏅?- `retry_failed_delay_seconds`锛氬喎鍗寸粨鏉熷悗棰濆绛夊緟绉掓暟锛岄伩鍏嶅垰鎭㈠灏辩珛鍗抽噸鏂拌姹?- `retry_failed_max_count`锛氬崟娆℃渶澶氶噸璇曞け璐ユ暣鐞嗘潯鏁帮紝璁句负 `0` 琛ㄧず涓嶉檺鍒?
## 鍙戝竷璇存槑

濡傛灉浣跨敤 `D:\寮€鍙慭github鍙戝竷\mp_plugin_market_publisher.py` 鍙戝竷锛屽缓璁墽琛岋細

```powershell
python D:\寮€鍙慭github鍙戝竷\mp_plugin_market_publisher.py publish `
  --plugin-source D:\寮€鍙慭MP鎻掍欢\u115椋庢帶鍙傛暟\u115riskcontrol `
  --repo-url https://github.com/<浣犵殑鐢ㄦ埛鍚?/<浣犵殑鎻掍欢浠撳簱> `
  --package-version base `
  --labels 宸ュ叿,115,椋庢帶 `
  --icon-source D:\寮€鍙慭MP鎻掍欢\u115椋庢帶鍙傛暟\u115riskcontrol\U115RiskControl.jpg `
  --history-note "棣栦釜鐗堟湰锛氭彁渚?u115 椋庢帶鍙傛暟鎸佷箙鍖栭厤缃?
```


