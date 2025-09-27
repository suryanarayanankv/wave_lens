#include <ESP_I2S.h>
#include "esp_camera.h"
#include "FS.h"
#include "SD.h"
#include "SPI.h"
#include <WiFi.h>
#include <HTTPClient.h>
#include <WebServer.h>
#include "time.h"

// ================== CONFIG ==================
#define WIFI_SSID     "POCO X5 Pro 5G"
#define WIFI_PASSWORD "Password"
#define SERVER_URL_AUDIO "http://10.242.254.30:8000/upload_raw"
#define SERVER_URL_IMAGE "http://10.242.254.30:8000/upload_image"

// Audio config
#define SAMPLE_RATE   16000U
#define SAMPLE_BITS   16
#define WAV_HEADER_SIZE 44
#define VOLUME_GAIN   2
#define RECORD_TIME   240  // max 240 seconds
#define SD_CS 21

// Streaming config
const char* STREAM_URL = "/stream";
const int STREAM_FRAMERATE = 10;

// Camera pins for XIAO ESP32S3
#define PWDN_GPIO_NUM     -1
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM 10
#define SIOD_GPIO_NUM 40
#define SIOC_GPIO_NUM 39
#define Y9_GPIO_NUM 48
#define Y8_GPIO_NUM 11
#define Y7_GPIO_NUM 12
#define Y6_GPIO_NUM 14
#define Y5_GPIO_NUM 16
#define Y4_GPIO_NUM 18
#define Y3_GPIO_NUM 17
#define Y2_GPIO_NUM 15
#define VSYNC_GPIO_NUM 38
#define HREF_GPIO_NUM 47
#define PCLK_GPIO_NUM 13
#define LED_GPIO_NUM 21
// ============================================

// Global variables
I2SClass I2S;
WebServer server(80);
uint32_t record_size = (SAMPLE_RATE * SAMPLE_BITS / 8) * RECORD_TIME;
File file;
String filename;
bool startRecording = false;
bool isRecording = false;
bool isStreaming = false;
int imageCount = 1;

const char* ntpServer = "pool.ntp.org";
const long  gmtOffset_sec = 19800;   // Indian timezone
const int   daylightOffset_sec = 0;

// ---------- Get current timestamp ----------
String getTimestamp() {
  struct tm timeinfo;
  if (!getLocalTime(&timeinfo)) {
    Serial.println("⚠️ Failed to obtain time");
    return "1970-01-01_00-00-00";
  }
  char buf[25];
  strftime(buf, sizeof(buf), "%Y-%m-%d_%H-%M-%S", &timeinfo);
  return String(buf);
}

// ---------- Video Streaming Handler ----------
void handleStream() {
  static char head[128];
  WiFiClient client = server.client();

  server.sendContent("HTTP/1.1 200 OK\r\n"
                     "Content-Type: multipart/x-mixed-replace; "
                     "boundary=frame\r\n\r\n");

  Serial.println("📹 Client connected to stream");

  while (client.connected() && isStreaming) {
    camera_fb_t *fb = esp_camera_fb_get();
    if (fb) {
      sprintf(head,
              "--frame\r\n"
              "Content-Type: image/jpeg\r\n"
              "Content-Length: %d\r\n\r\n",
              fb->len);
      client.write(head, strlen(head));
      client.write(fb->buf, fb->len);
      client.write("\r\n");
      esp_camera_fb_return(fb);
      delay(1000 / STREAM_FRAMERATE);
    } else {
      Serial.println("⚠️ Camera capture failed during streaming");
      break;
    }
  }
  
  Serial.println("📹 Client disconnected from stream");
}

// ---------- Start/Stop Streaming ----------
void startStreaming() {
  if (!isStreaming) {
    isStreaming = true;
    server.on(STREAM_URL, handleStream);
    Serial.println("🎬 Video streaming started!");
    Serial.printf("📺 Stream URL: http://%s%s\n", WiFi.localIP().toString().c_str(), STREAM_URL);
  } else {
    Serial.println("⚠️ Streaming already active");
  }
}

void stopStreaming() {
  if (isStreaming) {
    isStreaming = false;
    Serial.println("⏹️ Video streaming stopped!");
  } else {
    Serial.println("⚠️ No active streaming to stop");
  }
}

// ---------- Generate WAV header ----------
void generate_wav_header(uint8_t *wav_header, uint32_t wav_size, uint32_t sample_rate) {
  uint32_t file_size = wav_size + WAV_HEADER_SIZE - 8;
  uint32_t byte_rate = SAMPLE_RATE * SAMPLE_BITS / 8;
  const uint8_t set_wav_header[] = {
    'R','I','F','F',
    file_size, file_size>>8, file_size>>16, file_size>>24,
    'W','A','V','E',
    'f','m','t',' ',
    0x10,0x00,0x00,0x00,
    0x01,0x00,
    0x01,0x00,
    sample_rate, sample_rate>>8, sample_rate>>16, sample_rate>>24,
    byte_rate, byte_rate>>8, byte_rate>>16, byte_rate>>24,
    0x02,0x00,
    0x10,0x00,
    'd','a','t','a',
    wav_size, wav_size>>8, wav_size>>16, wav_size>>24,
  };
  memcpy(wav_header, set_wav_header, sizeof(set_wav_header));
}

// ---------- Upload audio file ----------
void uploadAudioFile(String filepath) {
  File audioFile = SD.open(filepath, FILE_READ);
  if (!audioFile) {
    Serial.println("⚠️ Failed to open audio file for upload");
    return;
  }

  HTTPClient http;
  WiFiClient client;

  String justName = filepath.substring(filepath.lastIndexOf("/") + 1);
  Serial.println("📤 Uploading audio: " + filepath);

  if (http.begin(client, SERVER_URL_AUDIO)) {
    http.addHeader("Content-Type", "audio/wav");
    http.addHeader("X-Filename", justName);

    int httpResponseCode = http.sendRequest("POST", &audioFile, audioFile.size());

    if (httpResponseCode > 0) {
      Serial.printf("✅ Audio upload OK, Response: %d\n", httpResponseCode);
      String response = http.getString();
      Serial.println("Server says: " + response);
    } else {
      Serial.printf("❌ Audio upload failed, Error: %s\n", http.errorToString(httpResponseCode).c_str());
    }
    http.end();
  }
  audioFile.close();
}

// ---------- Take and upload photo ----------
void takePhoto() {
  Serial.println("📸 Taking photo...");
  
  // Take a photo
  camera_fb_t *fb = esp_camera_fb_get();
  if(!fb){
    Serial.println("❌ Camera capture failed");
    return;
  }

  // Create filename with timestamp
  String timestamp = getTimestamp();
  String imageFilename = "/photos/photo_" + timestamp + ".jpg";
  
  // Save locally
  File imageFile = SD.open(imageFilename, FILE_WRITE);
  if(imageFile){
    imageFile.write(fb->buf, fb->len);
    imageFile.close();
    Serial.printf("✅ Photo saved: %s\n", imageFilename.c_str());
  } else {
    Serial.println("❌ Failed to save photo locally");
    esp_camera_fb_return(fb);
    return;
  }
  
  // Upload to server
  if(WiFi.status() == WL_CONNECTED){
    HTTPClient http;
    WiFiClient client;
    
    Serial.println("📤 Uploading photo...");
    
    if(http.begin(client, SERVER_URL_IMAGE)) {
      http.addHeader("Content-Type", "image/jpeg");
      
      // Open saved file for upload
      File uploadFile = SD.open(imageFilename, FILE_READ);
      if(uploadFile){
        int httpResponseCode = http.sendRequest("POST", &uploadFile, uploadFile.size());
        if(httpResponseCode > 0){
          Serial.printf("✅ Photo upload OK, Response: %d\n", httpResponseCode);
          String response = http.getString();
          Serial.println("Server says: " + response);
        } else {
          Serial.printf("❌ Photo upload failed: %s\n", http.errorToString(httpResponseCode).c_str());
        }
        uploadFile.close();
      }
      http.end();
    }
  } else {
    Serial.println("❌ WiFi not connected, photo upload skipped");
  }
  
  esp_camera_fb_return(fb);
  imageCount++;
}

// ---------- List files ----------
void listDir(fs::FS &fs, const char * dirname, uint8_t levels) {
  Serial.printf("Listing directory: %s\n", dirname);
  File root = fs.open(dirname);
  if (!root) {
    Serial.println("Failed to open directory");
    return;
  }
  if (!root.isDirectory()) {
    Serial.println("Not a directory");
    return;
  }
  File file = root.openNextFile();
  while (file) {
    if (file.isDirectory()) {
      Serial.print("  DIR : ");
      Serial.println(file.name());
      if (levels) {
        listDir(fs, file.path(), levels -1);
      }
    } else {
      Serial.print("  FILE: ");
      Serial.print(file.name());
      Serial.print("  SIZE: ");
      Serial.println(file.size());
    }
    file = root.openNextFile();
  }
}

// ---------- Audio Recording Task ----------
void i2s_adc(void *arg) {
  while (1) {
    // Wait for start command
    if (!startRecording) {
      vTaskDelay(100);
      continue;
    }

    startRecording = false;
    isRecording = true;

    uint32_t sample_size = 0;
    uint8_t *rec_buffer = NULL;

    // Timestamp filename
    filename = "/audio_history/recording_" + getTimestamp() + ".wav";

    Serial.printf("🎙️ Recording started: %s\n", filename.c_str());

    File file = SD.open(filename, FILE_WRITE);

    // Write WAV header
    uint8_t wav_header[WAV_HEADER_SIZE];
    generate_wav_header(wav_header, record_size, SAMPLE_RATE);
    file.write(wav_header, WAV_HEADER_SIZE);

    rec_buffer = (uint8_t *)ps_malloc(record_size);
    if (rec_buffer == NULL) {
      Serial.printf("malloc failed!\n");
      isRecording = false;
      continue;
    }

    unsigned long start_time = millis();
    uint32_t total_recorded = 0;

    while (isRecording && (millis() - start_time) < (RECORD_TIME * 1000)) {
      uint32_t chunk_size = SAMPLE_RATE * SAMPLE_BITS / 8; // 1 second
      sample_size = I2S.readBytes((char*)(rec_buffer + total_recorded), chunk_size);
      total_recorded += sample_size;

      if (total_recorded >= record_size) break;

      Serial.printf("Recording... %lu seconds\n", (millis() - start_time) / 1000);
      vTaskDelay(10);
    }

    // Apply gain
    for (uint32_t i = 0; i < total_recorded; i += SAMPLE_BITS/8) {
      (*(uint16_t *)(rec_buffer+i)) <<= VOLUME_GAIN;
    }

    // Write data to file
    file.write(rec_buffer, total_recorded);

    free(rec_buffer);
    file.close();
    isRecording = false;

    Serial.printf("✅ Recording saved: %s (%u bytes)\n", filename.c_str(), total_recorded);

    // Auto-upload after recording
    uploadAudioFile(filename);
  }
}

// ---------- Setup ----------
void setup() {
  Serial.begin(115200);
  while (!Serial);

  // WiFi
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("🌐 Connecting to WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\n✅ WiFi connected");
  Serial.printf("📍 IP Address: %s\n", WiFi.localIP().toString().c_str());

  // Time
  configTime(gmtOffset_sec, daylightOffset_sec, ntpServer);

  // I2S for audio
  I2S.setPinsPdmRx(42, 41);
  if (!I2S.begin(I2S_MODE_PDM_RX, 16000, I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_MONO)) {
    Serial.println("Failed to initialize I2S!");
    while (1);
  }

  // Camera initialization
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;
  config.pin_sscb_sda = SIOD_GPIO_NUM;
  config.pin_sscb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;
  config.frame_size = FRAMESIZE_SVGA;
  config.fb_location = CAMERA_FB_IN_PSRAM;
  config.jpeg_quality = 12;
  config.fb_count = 1;

  if(esp_camera_init(&config) != ESP_OK){
    Serial.println("❌ Camera init failed!");
    while(1);
  }
  Serial.println("✅ Camera initialized");

  // SD Card
  if (!SD.begin(SD_CS)) {
    Serial.println("❌ Failed to mount SD Card!");
    while (1);
  }
  Serial.println("✅ SD Card mounted");

  // Create directories if they don't exist
  if (!SD.exists("/audio_history")) {
    SD.mkdir("/audio_history");
    Serial.println("📁 Created audio_history folder");
  }
  
  if (!SD.exists("/photos")) {
    SD.mkdir("/photos");
    Serial.println("📁 Created photos folder");
  }

  // Initialize web server
  server.begin();
  Serial.println("✅ Web server started");

  // Start audio recording task
  xTaskCreate(i2s_adc, "i2s_adc", 1024 * 8, NULL, 1, NULL);

  Serial.println("\n📋 Available Commands:");
  Serial.println("  'start'     - Begin audio recording");
  Serial.println("  'stop'      - Stop audio recording");
  Serial.println("  'snap'      - Take photo and upload");
  Serial.println("  'streaming' - Start video streaming");
  Serial.println("  'stopstream'- Stop video streaming");
  Serial.println("=======================================");
}

// ---------- Main Loop ----------
void loop() {
  // Handle web server clients
  server.handleClient();
  
  // Handle serial commands
  if (Serial.available()) {
    String command = Serial.readStringUntil('\n');
    command.trim();
    command.toLowerCase();

    if (command == "s" && !isRecording) {
      startRecording = true;
      Serial.println("🎙️ Starting audio recording...");
    }
    else if (command == "e" && isRecording) {
      isRecording = false;
      Serial.println("⏹️ Stopping audio recording...");
    }
    else if (command == "p") {
      takePhoto();
    }
    else if (command == "v") {
      startStreaming();
    }
    else if (command == "o") {
      stopStreaming();
    }
    else {
      Serial.println("❓ Unknown command. Available: start, stop, snap, streaming, stopstream");
    }
  }
}