# HTTPS SSE Streaming Configuration Guide

## ⚠️ CRITICAL: Nginx SSE Streaming Issues

**DO NOT USE NGINX** for HTTPS proxy to Open-WebUI or any SSE (Server-Sent Events) streaming application without extensive testing.

### The Problem

Nginx has fundamental issues with SSE streaming over HTTPS:

1. **Chunked Transfer Encoding Corruption**: Nginx passes raw HTTP chunk size indicators (`de`, `cf`, `1a`, etc.) into the SSE stream, breaking JSON parsing
2. **Error Symptom**: `JSON.parse: unexpected character at line 1 column 1 of the JSON data`
3. **Multiple Buffer Settings Don't Help**: Even with `proxy_buffering off`, `gzip off`, etc., the chunked encoding still breaks through
4. **HTTP/2 Doesn't Solve It**: Even forcing HTTP/2 doesn't reliably fix the issue

### Why HTTP Works But HTTPS Doesn't

- **HTTP (port 3000)**: Direct connection to Docker container → Perfect streaming ✅
- **HTTPS via nginx (port 8080)**: Nginx proxy corrupts SSE chunks → Broken ❌
- **HTTPS via Apache (port 8080)**: Apache handles SSE correctly → Perfect streaming ✅

---

## ✅ RECOMMENDED: Apache Configuration

Apache handles SSE streaming flawlessly with zero configuration issues.

### Installation (Ubuntu/Debian)

```bash
# Install Apache
sudo apt update
sudo apt install -y apache2

# Stop nginx if running
sudo systemctl stop nginx
sudo systemctl disable nginx

# Enable required modules
sudo a2enmod ssl
sudo a2enmod proxy
sudo a2enmod proxy_http
sudo a2enmod proxy_wstunnel
sudo a2enmod rewrite
sudo a2enmod headers
```

### Apache Virtual Host Configuration

**File: `/etc/apache2/sites-available/openwebui-8080.conf`**

```apache
<VirtualHost *:8080>
    ServerName localhost

    # SSL Configuration
    SSLEngine on
    SSLCertificateFile /etc/ssl/certs/nginx-selfsigned.crt
    SSLCertificateKeyFile /etc/ssl/private/nginx-selfsigned.key

    # Proxy to Open-WebUI Docker container
    ProxyPreserveHost On
    ProxyPass / http://127.0.0.1:3000/
    ProxyPassReverse / http://127.0.0.1:3000/

    # SSE/Streaming support (CRITICAL)
    ProxyTimeout 3600

    # WebSocket support
    RewriteEngine On
    RewriteCond %{HTTP:Upgrade} websocket [NC]
    RewriteCond %{HTTP:Connection} upgrade [NC]
    RewriteRule ^/?(.*) "ws://127.0.0.1:3000/$1" [P,L]

    # Logging
    ErrorLog ${APACHE_LOG_DIR}/openwebui-error.log
    CustomLog ${APACHE_LOG_DIR}/openwebui-access.log combined
</VirtualHost>
```

### Enable and Start

```bash
# Add port 8080 to Apache
echo "Listen 8080" | sudo tee -a /etc/apache2/ports.conf

# Enable site
sudo a2ensite openwebui-8080.conf

# Disable default sites
sudo a2dissite 000-default.conf
sudo a2dissite default-ssl.conf

# Test and restart
sudo apache2ctl configtest
sudo systemctl restart apache2
sudo systemctl enable apache2
```

### Self-Signed Certificate (Development)

```bash
# Generate self-signed certificate (valid 1 year)
sudo openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout /etc/ssl/private/nginx-selfsigned.key \
  -out /etc/ssl/certs/nginx-selfsigned.crt \
  -subj "/C=US/ST=State/L=City/O=Organization/OU=IT/CN=localhost/emailAddress=admin@localhost"

# Set permissions
sudo chmod 600 /etc/ssl/private/nginx-selfsigned.key
```

---

## ❌ Nginx (Not Recommended for SSE)

If you **must** use nginx, be aware of severe limitations with SSE streaming over HTTPS.

### Known Issues

| Issue | Impact | Workaround |
|-------|--------|------------|
| Chunked encoding corruption | JSON parse errors | **None reliable** |
| Buffer settings ineffective | Streaming breaks | Switch to Apache |
| HTTP/2 doesn't help | Still corrupts SSE | Switch to Apache |
| Complex troubleshooting | Days wasted | Switch to Apache |

### If You Must Use Nginx

We tested **20+ different nginx configurations** over 3 days. None worked reliably for HTTPS SSE streaming. HTTP worked fine, but HTTPS consistently broke.

**Our recommendation: Don't use nginx for SSE over HTTPS.**

---

## 🧪 Testing Your Setup

### Test HTTPS Streaming

```bash
# Should see clean SSE format with "data:" prefix
curl -k -s -N https://localhost:8080/api/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "model": "RAICA-Model1",
    "messages": [{"role": "user", "content": "hello"}],
    "stream": true
  }'
```

### Expected Output (Apache - CORRECT ✅)

```
data: {"id": "chatcmpl-123", "object": "chat.completion.chunk", "created": 1234567890, "model": "...", "choices": [...]}

data: {"id": "chatcmpl-123", "object": "chat.completion.chunk", "created": 1234567890, "model": "...", "choices": [...]}

data: [DONE]
```

### Broken Output (Nginx - WRONG ❌)

```
de
data: {"id": "chatcmpl-123", ...}

1


cf
data: {"id": "chatcmpl-123", ...}
```

Notice the hex numbers (`de`, `cf`, `1`) - these are chunk size indicators that nginx incorrectly passes through.

---

## 📊 Performance Comparison

| Metric | HTTP:3000 | Apache HTTPS:8080 | Nginx HTTPS:8080 |
|--------|-----------|-------------------|------------------|
| **Streaming** | ✅ Perfect | ✅ Perfect | ❌ Broken |
| **Speed** | Fast | Fast | N/A (broken) |
| **Reliability** | 100% | 100% | 0% |
| **Setup Time** | 0min | 5min | 3 days (failed) |

---

## 🔐 Why HTTPS Matters

Browser APIs that **require HTTPS**:
- Speech-to-Text (Web Speech API)
- Text-to-Speech
- Camera/Microphone access
- Geolocation (in some browsers)
- Service Workers
- Push Notifications

**Without HTTPS**, these features won't work even on localhost (except Chrome with special flags).

---

## 💡 Production Recommendations

1. **Use Apache** for HTTPS termination (proven, reliable)
2. **Use Let's Encrypt** for production certificates (free, auto-renewal)
3. **Direct HTTP** for internal services (if SSL termination happens at load balancer)
4. **Avoid nginx** for SSE applications unless you have dedicated DevOps to troubleshoot

---

## 📚 Related Issues

- Open-WebUI showing `{}` with no response
- `JSON.parse: unexpected character` errors
- Streaming works on HTTP but not HTTPS
- Response appears in nginx logs but not in browser
- Firefox/Chrome showing different errors

**Root Cause:** Nginx chunked transfer encoding corruption (not your application!)

---

## 🎯 Time Investment Comparison

| Approach | Setup Time | Debugging Time | Result |
|----------|------------|----------------|---------|
| Apache | 5 minutes | 0 minutes | ✅ Works perfectly |
| Nginx | 30 minutes | **3 days** | ❌ Still broken |

**Lesson Learned:** Use the right tool for the job. Apache excels at SSE streaming.

---

## 🚨 Red Flag Warning

**If you see this error with nginx + HTTPS + SSE:**
```
JSON.parse: unexpected character at line 1 column 1 of the JSON data
```

**Don't waste time debugging nginx.** Switch to Apache immediately.

---

*Last Updated: 2025-11-12*
*Tested With: Open-WebUI, Apache 2.4.x, Ubuntu 24.04*
