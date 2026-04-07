// UV + Atmospheric Pressure + Ozone + RTC + EEPROM + microSD data logger
// Arduino Pro Mini (ATmega328PB, 3.3V/8MHz)
// LTR390 (0x53) + MS5611 (0x76) + SEN0321 (0x73) + DS3231 (0x68) + AT24C256 (0x50) over shared I2C
// LaskaKit microSD module on SPI (CS = D10)
//
// Data is written to EEPROM (primary) and microSD (backup) simultaneously.
// microSD stores human-readable CSV files named by date (e.g. 20260325.CSV).
//
// Serial commands:
//   record <seconds>  - start recording at given interval (default 10s)
//   stop              - stop recording
//   dump              - dump all EEPROM records as CSV
//   dumpsd            - dump current day's SD file over serial
//   status            - show EEPROM + SD usage
//   clear             - erase all EEPROM records
//   settime YYYY MM DD HH MM SS - set RTC time

#include <Wire.h>
#include <SPI.h>
#include <SD.h>
#include <LTR390.h>
#include <MS5611.h>
#include <DFRobot_OzoneSensor.h>
#include <RTClib.h>

#define COLLECT_NUMBER 20  // ozone averaging sample count (1-100)

// AT24C256 EEPROM config
#define EEPROM_ADDR       0x50
#define EEPROM_SIZE       32768UL  // 32KB
#define HEADER_SIZE       8        // 4 bytes record count + 4 bytes next write addr
#define RECORD_SIZE       34       // bytes per data record
#define MAX_RECORDS       ((EEPROM_SIZE - HEADER_SIZE) / RECORD_SIZE)
#define EEPROM_PAGE_SIZE  64

// microSD config
#define SD_CS_PIN         10

// Serial command buffer
#define CMD_BUF_SIZE      48
char cmdBuf[CMD_BUF_SIZE];
uint8_t cmdIdx = 0;

LTR390 ltr390;
MS5611 ms5611(0x76);
DFRobot_OzoneSensor ozone;
RTC_DS3231 rtc;

bool recording = false;
uint16_t recordInterval = 10;  // seconds between recordings
unsigned long lastRecordTime = 0;
uint32_t recordCount = 0;
uint32_t nextWriteAddr = HEADER_SIZE;
bool sdAvailable = false;

// --- AT24C256 low-level functions ---

void eepromWriteByte(uint16_t addr, uint8_t data) {
  Wire.beginTransmission((uint8_t)EEPROM_ADDR);
  Wire.write((uint8_t)(addr >> 8));
  Wire.write((uint8_t)(addr & 0xFF));
  Wire.write(data);
  Wire.endTransmission();
  delay(5);
}

uint8_t eepromReadByte(uint16_t addr) {
  Wire.beginTransmission((uint8_t)EEPROM_ADDR);
  Wire.write((uint8_t)(addr >> 8));
  Wire.write((uint8_t)(addr & 0xFF));
  Wire.endTransmission();
  Wire.requestFrom((uint8_t)EEPROM_ADDR, (uint8_t)1);
  return Wire.available() ? Wire.read() : 0xFF;
}

void eepromWriteBlock(uint16_t addr, const uint8_t *data, uint8_t len) {
  while (len > 0) {
    uint8_t pageRemaining = EEPROM_PAGE_SIZE - (addr % EEPROM_PAGE_SIZE);
    uint8_t chunk = min(len, pageRemaining);
    chunk = min(chunk, (uint8_t)30);

    Wire.beginTransmission((uint8_t)EEPROM_ADDR);
    Wire.write((uint8_t)(addr >> 8));
    Wire.write((uint8_t)(addr & 0xFF));
    for (uint8_t i = 0; i < chunk; i++) {
      Wire.write(data[i]);
    }
    Wire.endTransmission();
    delay(5);

    addr += chunk;
    data += chunk;
    len -= chunk;
  }
}

void eepromReadBlock(uint16_t addr, uint8_t *data, uint8_t len) {
  while (len > 0) {
    uint8_t chunk = min(len, (uint8_t)30);

    Wire.beginTransmission((uint8_t)EEPROM_ADDR);
    Wire.write((uint8_t)(addr >> 8));
    Wire.write((uint8_t)(addr & 0xFF));
    Wire.endTransmission();

    Wire.requestFrom((uint8_t)EEPROM_ADDR, chunk);
    for (uint8_t i = 0; i < chunk && Wire.available(); i++) {
      data[i] = Wire.read();
    }

    addr += chunk;
    data += chunk;
    len -= chunk;
  }
}

// --- EEPROM header management ---

void writeHeader() {
  uint8_t buf[8];
  memcpy(buf, &recordCount, 4);
  memcpy(buf + 4, &nextWriteAddr, 4);
  eepromWriteBlock(0, buf, 8);
}

void readHeader() {
  uint8_t buf[8];
  eepromReadBlock(0, buf, 8);
  memcpy(&recordCount, buf, 4);
  memcpy(&nextWriteAddr, buf + 4, 4);

  if (recordCount > MAX_RECORDS || nextWriteAddr > EEPROM_SIZE) {
    recordCount = 0;
    nextWriteAddr = HEADER_SIZE;
    writeHeader();
  }
}

// --- Print a DateTime as YYYY/MM/DD HH:MM:SS ---

void printDateTime(Print &out, const DateTime &dt) {
  out.print(dt.year());
  out.print('/');
  if (dt.month() < 10) out.print('0');
  out.print(dt.month());
  out.print('/');
  if (dt.day() < 10) out.print('0');
  out.print(dt.day());
  out.print(' ');
  if (dt.hour() < 10) out.print('0');
  out.print(dt.hour());
  out.print(':');
  if (dt.minute() < 10) out.print('0');
  out.print(dt.minute());
  out.print(':');
  if (dt.second() < 10) out.print('0');
  out.print(dt.second());
}

// --- Build SD filename from DateTime: "YYYYMMDD.CSV" ---

void getSDFilename(const DateTime &dt, char *buf) {
  // Manual number-to-string to avoid sprintf format string in RAM
  uint16_t y = dt.year();
  buf[0] = '0' + (y / 1000);
  buf[1] = '0' + (y / 100 % 10);
  buf[2] = '0' + (y / 10 % 10);
  buf[3] = '0' + (y % 10);
  buf[4] = '0' + (dt.month() / 10);
  buf[5] = '0' + (dt.month() % 10);
  buf[6] = '0' + (dt.day() / 10);
  buf[7] = '0' + (dt.day() % 10);
  buf[8] = '.';
  buf[9] = 'C';
  buf[10] = 'S';
  buf[11] = 'V';
  buf[12] = '\0';
}

// --- SD card helpers ---

void sdWriteHeaderIfNew(const char *filename) {
  if (!sdAvailable) return;
  if (!SD.exists(filename)) {
    File f = SD.open(filename, FILE_WRITE);
    if (f) {
      f.println(F("timestamp,als,lux,uvs,uvi,temp_c,pressure_mbar,ozone_ppb,rtc_temp_c"));
      f.close();
    }
  }
}

void sdWriteRecord(const DateTime &dt, uint32_t als, float lux,
                   uint32_t uvs, float uvi, float temperature,
                   float pressure, int16_t ozonePpb, float rtcTemp) {
  if (!sdAvailable) return;

  char filename[13];
  getSDFilename(dt, filename);
  sdWriteHeaderIfNew(filename);

  File f = SD.open(filename, FILE_WRITE);
  if (f) {
    printDateTime(f, dt);
    f.print(',');
    f.print(als);
    f.print(',');
    f.print(lux, 2);
    f.print(',');
    f.print(uvs);
    f.print(',');
    f.print(uvi, 2);
    f.print(',');
    f.print(temperature, 2);
    f.print(',');
    f.print(pressure, 2);
    f.print(',');
    f.print(ozonePpb);
    f.print(',');
    f.println(rtcTemp, 2);
    f.close();
  } else {
    Serial.println(F("SD write failed!"));
  }
}

// --- EEPROM record functions ---

bool writeRecord(uint32_t timestamp, uint32_t als, float lux,
                 uint32_t uvs, float uvi, float temperature,
                 float pressure, int16_t ozonePpb, float rtcTemp) {
  if (recordCount >= MAX_RECORDS) {
    Serial.println(F("EEPROM full!"));
    return false;
  }

  uint8_t buf[RECORD_SIZE];
  uint8_t offset = 0;

  memcpy(buf + offset, &timestamp, 4);    offset += 4;
  memcpy(buf + offset, &als, 4);          offset += 4;
  memcpy(buf + offset, &lux, 4);          offset += 4;
  memcpy(buf + offset, &uvs, 4);          offset += 4;
  memcpy(buf + offset, &uvi, 4);          offset += 4;
  memcpy(buf + offset, &temperature, 4);  offset += 4;
  memcpy(buf + offset, &pressure, 4);     offset += 4;
  memcpy(buf + offset, &ozonePpb, 2);     offset += 2;
  memcpy(buf + offset, &rtcTemp, 4);      offset += 4;

  eepromWriteBlock(nextWriteAddr, buf, RECORD_SIZE);

  nextWriteAddr += RECORD_SIZE;
  recordCount++;
  writeHeader();

  return true;
}

void dumpRecords() {
  if (recordCount == 0) {
    Serial.println(F("No EEPROM records stored."));
    return;
  }

  Serial.println(F("timestamp,als,lux,uvs,uvi,temp_c,pressure_mbar,ozone_ppb,rtc_temp_c"));

  uint16_t addr = HEADER_SIZE;
  for (uint32_t i = 0; i < recordCount; i++) {
    uint8_t buf[RECORD_SIZE];
    eepromReadBlock(addr, buf, RECORD_SIZE);

    uint32_t timestamp, als, uvs;
    float lux, uvi, temperature, pressure, rtcTemp;
    int16_t ozonePpb;
    uint8_t offset = 0;

    memcpy(&timestamp, buf + offset, 4);    offset += 4;
    memcpy(&als, buf + offset, 4);          offset += 4;
    memcpy(&lux, buf + offset, 4);          offset += 4;
    memcpy(&uvs, buf + offset, 4);          offset += 4;
    memcpy(&uvi, buf + offset, 4);          offset += 4;
    memcpy(&temperature, buf + offset, 4);  offset += 4;
    memcpy(&pressure, buf + offset, 4);     offset += 4;
    memcpy(&ozonePpb, buf + offset, 2);     offset += 2;
    memcpy(&rtcTemp, buf + offset, 4);      offset += 4;

    DateTime dt(timestamp);
    printDateTime(Serial, dt);

    Serial.print(',');
    Serial.print(als);
    Serial.print(',');
    Serial.print(lux, 2);
    Serial.print(',');
    Serial.print(uvs);
    Serial.print(',');
    Serial.print(uvi, 2);
    Serial.print(',');
    Serial.print(temperature, 2);
    Serial.print(',');
    Serial.print(pressure, 2);
    Serial.print(',');
    Serial.print(ozonePpb);
    Serial.print(',');
    Serial.println(rtcTemp, 2);

    addr += RECORD_SIZE;
  }

  Serial.print(F("Total: "));
  Serial.print(recordCount);
  Serial.println(F(" records"));
}

void dumpSDFile(const DateTime &dt) {
  if (!sdAvailable) {
    Serial.println(F("SD card not available."));
    return;
  }

  char filename[13];
  getSDFilename(dt, filename);

  if (!SD.exists(filename)) {
    Serial.print(F("File not found: "));
    Serial.println(filename);
    return;
  }

  Serial.print(F("--- "));
  Serial.print(filename);
  Serial.println(F(" ---"));

  File f = SD.open(filename, FILE_READ);
  if (f) {
    unsigned long sz = f.size();
    while (f.available()) {
      Serial.write(f.read());
    }
    f.close();
    Serial.print(F("--- end ("));
    Serial.print(sz);
    Serial.println(F(" bytes) ---"));
  } else {
    Serial.println(F("SD read failed!"));
  }
}

void clearRecords() {
  recordCount = 0;
  nextWriteAddr = HEADER_SIZE;
  writeHeader();
  Serial.println(F("EEPROM cleared."));
}

void printStatus() {
  Serial.println(F("== EEPROM =="));
  Serial.print(F("Records: "));
  Serial.print(recordCount);
  Serial.print(F(" / "));
  Serial.println(MAX_RECORDS);
  Serial.print(F("Used: "));
  Serial.print(nextWriteAddr);
  Serial.print(F(" / "));
  Serial.print(EEPROM_SIZE);
  Serial.println(F(" bytes"));

  Serial.println(F("== microSD =="));
  if (sdAvailable) {
    Serial.println(F("Status: OK"));
    DateTime now = rtc.now();
    char filename[13];
    getSDFilename(now, filename);
    if (SD.exists(filename)) {
      File f = SD.open(filename, FILE_READ);
      if (f) {
        Serial.print(F("Today ("));
        Serial.print(filename);
        Serial.print(F("): "));
        Serial.print(f.size());
        Serial.println(F(" bytes"));
        f.close();
      }
    } else {
      Serial.print(F("Today ("));
      Serial.print(filename);
      Serial.println(F("): no file yet"));
    }
  } else {
    Serial.println(F("Status: NOT AVAILABLE"));
  }

  Serial.print(F("Recording: "));
  Serial.println(recording ? F("ON") : F("OFF"));
  if (recording) {
    Serial.print(F("Interval: "));
    Serial.print(recordInterval);
    Serial.println('s');
  }
}

// --- Serial command parser (no String class - uses char buffer) ---

int parseIntAt(const char *buf, uint8_t *pos) {
  while (buf[*pos] == ' ') (*pos)++;
  int val = 0;
  while (buf[*pos] >= '0' && buf[*pos] <= '9') {
    val = val * 10 + (buf[*pos] - '0');
    (*pos)++;
  }
  return val;
}

void processCommand(const char *cmd) {
  while (*cmd == ' ') cmd++;

  if (strncmp_P(cmd, PSTR("record"), 6) == 0) {
    if (cmd[6] == ' ') {
      uint8_t pos = 7;
      int val = parseIntAt(cmd, &pos);
      if (val > 0) recordInterval = val;
    }
    recording = true;
    lastRecordTime = 0;
    Serial.print(F("Recording started, interval: "));
    Serial.print(recordInterval);
    Serial.println('s');
  }
  else if (strcmp_P(cmd, PSTR("stop")) == 0) {
    recording = false;
    Serial.println(F("Recording stopped."));
  }
  else if (strcmp_P(cmd, PSTR("dump")) == 0) {
    dumpRecords();
  }
  else if (strncmp_P(cmd, PSTR("dumpsd"), 6) == 0) {
    if (cmd[6] == ' ') {
      uint8_t pos = 7;
      int y = parseIntAt(cmd, &pos);
      int m = parseIntAt(cmd, &pos);
      int d = parseIntAt(cmd, &pos);
      DateTime dt(y, m, d, 0, 0, 0);
      dumpSDFile(dt);
    } else {
      DateTime now = rtc.now();
      dumpSDFile(now);
    }
  }
  else if (strcmp_P(cmd, PSTR("status")) == 0) {
    printStatus();
  }
  else if (strcmp_P(cmd, PSTR("clear")) == 0) {
    recording = false;
    clearRecords();
  }
  else if (strncmp_P(cmd, PSTR("settime"), 7) == 0) {
    uint8_t pos = 8;
    int parts[6];
    for (uint8_t i = 0; i < 6; i++) {
      parts[i] = parseIntAt(cmd, &pos);
    }
    rtc.adjust(DateTime(parts[0], parts[1], parts[2], parts[3], parts[4], parts[5]));
    Serial.println(F("RTC time set."));
  }
  else {
    Serial.println(F("Commands: record [sec], stop, dump, dumpsd [YYYY MM DD], status, clear, settime YYYY MM DD HH MM SS"));
  }
}

// --- Setup & Loop ---

void setup() {
  Serial.begin(9600);

  Wire.begin();

  // Init LTR390
  if (!ltr390.init()) {
    Serial.println(F("LTR390 not found!"));
    while (1) delay(1000);
  }

  ltr390.setGain(LTR390_GAIN_3);
  ltr390.setResolution(LTR390_RESOLUTION_18BIT);
  ltr390.enable(true);

  // Init MS5611
  if (!ms5611.begin()) {
    Serial.println(F("MS5611 not found!"));
    while (1) delay(1000);
  }

  // Init SEN0321 ozone sensor
  while (!ozone.begin(OZONE_ADDRESS_3)) {
    Serial.println(F("SEN0321 not found!"));
    delay(1000);
  }

  ozone.setModes(MEASURE_MODE_PASSIVE);

  // Init DS3231 RTC
  if (!rtc.begin()) {
    Serial.println(F("DS3231 not found!"));
    while (1) delay(1000);
  }

  if (rtc.lostPower()) {
    Serial.println(F("RTC lost power, setting compile time..."));
    rtc.adjust(DateTime(F(__DATE__), F(__TIME__)));
  }

  // Init AT24C256 EEPROM
  readHeader();

  // Init microSD
  if (SD.begin(SD_CS_PIN)) {
    sdAvailable = true;
    Serial.println(F("microSD ready"));
  } else {
    sdAvailable = false;
    Serial.println(F("microSD not found - no SD backup"));
  }

  Serial.println(F("All sensors + storage ready"));
  Serial.println(F("Ozone warming up (~3 min)..."));
  printStatus();
  Serial.println(F("Type 'record' to start, 'help' for cmds"));
}

void loop() {
  // Handle serial commands (char-by-char, no String class)
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (cmdIdx > 0) {
        cmdBuf[cmdIdx] = '\0';
        processCommand(cmdBuf);
        cmdIdx = 0;
      }
    } else if (cmdIdx < CMD_BUF_SIZE - 1) {
      cmdBuf[cmdIdx++] = c;
    }
  }

  // Read all sensors
  // sensor read cycle

  DateTime now = rtc.now();
  float rtcTemp = rtc.getTemperature();

  // Read UV
  ltr390.setMode(LTR390_MODE_UVS);
  delay(300);

  uint32_t uvs = 0;
  float uvi = 0;
  if (ltr390.newDataAvailable()) {
    uvs = ltr390.readUVS();
    uvi = ltr390.getUVI();
  }

  // Read ambient light
  ltr390.setMode(LTR390_MODE_ALS);
  delay(300);

  uint32_t als = 0;
  float lux = 0;
  if (ltr390.newDataAvailable()) {
    als = ltr390.readALS();
    lux = ltr390.getLux();
  }

  // Read pressure + temperature
  ms5611.read();
  float temperature = ms5611.getTemperature();
  float pressure = ms5611.getPressure();

  // Read ozone
  int16_t ozonePpb = ozone.readOzoneData(COLLECT_NUMBER);



  // Print live readings
  printDateTime(Serial, now);
  Serial.println();

  Serial.print(F("ALS: "));
  Serial.print(als);
  Serial.print(F(" Lux: "));
  Serial.print(lux);
  Serial.print(F(" | UVS: "));
  Serial.print(uvs);
  Serial.print(F(" UVI: "));
  Serial.println(uvi);

  Serial.print(F("T: "));
  Serial.print(temperature, 2);
  Serial.print(F("C | P: "));
  Serial.print(pressure, 2);
  Serial.println(F("mbar"));

  Serial.print(F("O3: "));
  Serial.print(ozonePpb);
  Serial.print(F("ppb | RTC: "));
  Serial.print(rtcTemp, 2);
  Serial.println('C');

  // Record to EEPROM + SD if active
  if (recording) {
    unsigned long now_ms = millis();
    if (lastRecordTime == 0 || (now_ms - lastRecordTime) >= (unsigned long)recordInterval * 1000UL) {
      lastRecordTime = now_ms;
      uint32_t unixTime = now.unixtime();

      bool eepromOk = writeRecord(unixTime, als, lux, uvs, uvi, temperature, pressure, ozonePpb, rtcTemp);

      sdWriteRecord(now, als, lux, uvs, uvi, temperature, pressure, ozonePpb, rtcTemp);

      if (eepromOk) {
        Serial.print(F("[REC #"));
        Serial.print(recordCount);
        if (sdAvailable) Serial.print(F("+SD"));
        Serial.println(']');
      }
    }
  }

  Serial.println(F("---"));

  delay(1000);
}
