"""Ingest resolved incidents into Chroma for RAG retrieval.

Run: python -m synapse.rag.ingest
"""
from __future__ import annotations
import asyncio
import logging
import uuid
from typing import Any

import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

from synapse.config import settings

logger = logging.getLogger(__name__)
COLLECTION_NAME = "incident_kb"

# ── Seed knowledge base ───────────────────────────────────────────────────────
# Format: {symptom, root_cause, remediation_id, resolution}
SEED_INCIDENTS: list[dict[str, str]] = [
    {
        "symptom": "Sales dashboard unreachable, users cannot access the sales dashboard application",
        "root_cause": "WEB-02 worker pool exhausted — too many concurrent connections caused all workers to hang",
        "remediation_id": "restart_web_service",
        "resolution": "Restart the web service on WEB-02 to clear worker pool exhaustion. Run: restart_web_service on host=WEB-02",
    },
    {
        "symptom": "DB connection pool exhausted on PostgreSQL primary, billing application extremely slow",
        "root_cause": "DB-01 connection pool limit reached — too many idle connections not being recycled",
        "remediation_id": "restart_db_connection_pool",
        "resolution": "Restart the DB connection pool manager to recycle stale connections. Run: restart_db_connection_pool on host=DB-01",
    },
    {
        "symptom": "Redis cache stampede causing high latency and CPU spikes on sales dashboard",
        "root_cause": "REDIS-01 cache keys expired simultaneously causing a thundering herd — cache stampede",
        "remediation_id": "clear_cache",
        "resolution": "Clear and reinitialize the Redis cache to break the stampede. Run: clear_cache on host=REDIS-01",
    },
    {
        "symptom": "Web server high CPU usage causing slow response times across all pages",
        "root_cause": "Worker threads spawned excessively due to a runaway background job consuming all CPU",
        "remediation_id": "restart_web_service",
        "resolution": "Restart the web service to kill runaway threads. Run: restart_web_service",
    },
    {
        "symptom": "Application returns 503 Service Unavailable errors intermittently",
        "root_cause": "Load balancer health checks failing due to backend server overload, routing to failed instances",
        "remediation_id": "restart_web_service",
        "resolution": "Restart overloaded backend web servers to restore health check compliance",
    },
    {
        "symptom": "Database queries timing out, application showing database connection errors",
        "root_cause": "Long-running queries blocking connection slots, connection pool starved",
        "remediation_id": "restart_db_connection_pool",
        "resolution": "Restart DB connection pool to terminate stale connections and allow new ones",
    },
    {
        "symptom": "CRM application login page loads very slowly or times out",
        "root_cause": "Auth service overloaded with too many simultaneous authentication requests",
        "remediation_id": "scale_workers",
        "resolution": "Scale up the authentication service workers to handle increased load",
    },
    {
        "symptom": "Billing application failing to process payments, timeout errors on checkout",
        "root_cause": "Message queue (RabbitMQ) backlog causing payment events to queue indefinitely",
        "remediation_id": "restart_db_connection_pool",
        "resolution": "Clear message queue backlog and restart processing workers",
    },
    {
        "symptom": "HR portal showing blank pages or partial data after recent deployment",
        "root_cause": "Database schema mismatch after migration — app reading stale cached schema",
        "remediation_id": "clear_cache",
        "resolution": "Clear application cache to force schema refresh from database",
    },
    {
        "symptom": "WEB-02 error rate spiking above 5%, multiple 500 errors in logs",
        "root_cause": "WEB-02 worker pool exhausted due to memory leak in request handler",
        "remediation_id": "restart_web_service",
        "resolution": "Restart web service on WEB-02 to free memory and reset worker pool",
    },
    {
        "symptom": "Network latency spiking between web servers and database, queries slow",
        "root_cause": "Core switch high packet loss due to spanning tree reconvergence",
        "remediation_id": "restart_web_service",
        "resolution": "Switch issue requires network team. Restart affected services as a workaround",
    },
    {
        "symptom": "Monitoring alerts not firing, Grafana dashboards showing stale data",
        "root_cause": "Prometheus scrape job failing due to target unreachable — metric endpoint down",
        "remediation_id": "restart_web_service",
        "resolution": "Restart the monitoring target service to restore metric endpoint",
    },
    {
        "symptom": "Sales dashboard slow to load charts, data appears outdated",
        "root_cause": "Redis cache serving expired data due to incorrect TTL configuration",
        "remediation_id": "clear_cache",
        "resolution": "Clear Redis cache and restart web service to force fresh data load",
    },
    {
        "symptom": "Application CPU at 100%, health checks failing",
        "root_cause": "Scale-out needed — current worker count insufficient for current load",
        "remediation_id": "scale_workers",
        "resolution": "Scale workers to distribute load. Run: scale_workers",
    },
    {
        "symptom": "Memory usage growing continuously on web server, out of memory errors",
        "root_cause": "Memory leak in web application worker process — workers never releasing memory",
        "remediation_id": "restart_web_service",
        "resolution": "Restart web service workers to reclaim leaked memory",
    },
    # Network issues (30 Incident Expansion)
    {
        "symptom": "I can't load any external websites, but local network fileshares are still working fine",
        "root_cause": "Primary gateway unresponsive or DNS servers misconfigured on the local interface",
        "remediation_id": "diagnose_internet",
        "resolution": "Run the internet diagnostics tool to check gateway routing and external link state.",
    },
    {
        "symptom": "Internet is completely down on my laptop after waking it up from sleep mode",
        "root_cause": "Network adapter power-saving state failed to wake up, causing driver lockup",
        "remediation_id": "reset_network_adapter",
        "resolution": "Reset the network adapter to reinitialize the hardware and driver state.",
    },
    {
        "symptom": "Can't connect to corporate intranet tools, keep getting connection timed out errors",
        "root_cause": "IPsec VPN tunnel terminated due to network interface IP address change",
        "remediation_id": "reconnect_vpn",
        "resolution": "Reconnect the corporate VPN tunnel to re-establish secure routing.",
    },
    {
        "symptom": "Web pages fail to load with DNS_PROBE_FINISHED_NXDOMAIN errors, but pinging 8.8.8.8 works",
        "root_cause": "Local DNS resolver cache has stale or corrupted records",
        "remediation_id": "flush_dns",
        "resolution": "Flush the local DNS resolver cache to force fresh domain name resolution.",
    },
    {
        "symptom": "WiFi shows connected but there is no internet access at all and pinging gateway fails",
        "root_cause": "TCP/IP stack corrupted or network configuration parameters out of sync",
        "remediation_id": "reset_network_stack",
        "resolution": "Reset the TCP/IP network stack and clear Winsock catalog to restore configuration.",
    },
    # POS / cashier specific
    {
        "symptom": "Cash register terminal is frozen on the checkout screen and won't respond to touch inputs",
        "root_cause": "Local POS desktop service thread deadlocked waiting for printer spooler response",
        "remediation_id": "restart_app_service",
        "resolution": "Restart the POS application service to release the deadlocked UI thread.",
    },
    {
        "symptom": "Card reader is not communicating with the cashier terminal, payment screen shows offline",
        "root_cause": "Local transaction broker service lost connection to the USB serial interface",
        "remediation_id": "restart_app_service",
        "resolution": "Restart the local POS application service to reconnect the card reader interface.",
    },
    {
        "symptom": "Receipt printer is not printing receipts even though it has paper and green light is on",
        "root_cause": "POS print spooler daemon hung during queue flush",
        "remediation_id": "restart_app_service",
        "resolution": "Restart the POS application service to clear the print spooler queue.",
    },
    {
        "symptom": "Barcode scanner beeped but the item did not appear in the checkout cart",
        "root_cause": "Input event listener service crashed or stopped processing keystrokes",
        "remediation_id": "restart_app_service",
        "resolution": "Restart the POS application service to restart the hardware input event listener.",
    },
    {
        "symptom": "Cashier terminal is extremely slow when looking up item codes from the local catalog",
        "root_cause": "POS local database cache bloated with outdated pricing records",
        "remediation_id": "clear_cache",
        "resolution": "Clear the local POS application cache to force a fresh catalog sync.",
    },
    # Web apps
    {
        "symptom": "Online store product page is showing old prices even after applying a store-wide discount",
        "root_cause": "Web application HTTP response cache is serving stale CDN cached copies of the product pages",
        "remediation_id": "clear_cache",
        "resolution": "Clear the application cache to purge outdated product pages and load updated pricing.",
    },
    {
        "symptom": "Customer portal shows 502 Bad Gateway error when clicking on the orders tab",
        "root_cause": "Upstream web server process crashed due to an unhandled exception in the response builder",
        "remediation_id": "restart_web_service",
        "resolution": "Restart the web service to spawn new, healthy worker processes.",
    },
    {
        "symptom": "File upload portal returns 504 Gateway Timeout when uploading documents",
        "root_cause": "Nginx reverse proxy terminated connection before backend web server finished processing",
        "remediation_id": "restart_web_service",
        "resolution": "Restart the web service to clear slow processing threads and reset connections.",
    },
    {
        "symptom": "User profile photos are not updating after uploading new images, old ones still appear",
        "root_cause": "Avatar image cache on the web server serving cached local files instead of fetching from storage",
        "remediation_id": "clear_cache",
        "resolution": "Clear the application cache to invalidate old avatar images.",
    },
    {
        "symptom": "Corporate portal home page loads with broken layout and missing stylesheet styles",
        "root_cause": "Stale CSS assets cached in memory after the latest rolling deployment",
        "remediation_id": "clear_cache",
        "resolution": "Clear the application cache to force loading of the newly deployed static assets.",
    },
    # Databases
    {
        "symptom": "Payment processing is failing with error: 'Too many open database connections'",
        "root_cause": "Database connection pool exhausted due to connections not being returned after transaction rollback",
        "remediation_id": "restart_db_connection_pool",
        "resolution": "Restart the database connection pool to reclaim leaked database connections.",
    },
    {
        "symptom": "Reports page is extremely slow, queries that usually take seconds are taking minutes",
        "root_cause": "Database connection pool queue is backlogged with long-running analytical queries",
        "remediation_id": "restart_db_connection_pool",
        "resolution": "Restart the database connection pool to terminate slow queries and free up connections.",
    },
    {
        "symptom": "Shopping cart checkout fails with database connection timeout error",
        "root_cause": "Connection pool driver timed out waiting for an available connection from the database pool",
        "remediation_id": "restart_db_connection_pool",
        "resolution": "Restart the database connection pool to reset and clean up active connections.",
    },
    {
        "symptom": "Admin panel dashboard is throwing internal server error: 'OperationalError: connection refused'",
        "root_cause": "Local database socket pool manager crashed, preventing application connections",
        "remediation_id": "restart_db_connection_pool",
        "resolution": "Restart the database connection pool to reinitialize socket connections.",
    },
    {
        "symptom": "User registration page returns 500 error stating database transaction pool is full",
        "root_cause": "Pool exhaustion due to uncommitted transactions blocking the pool queue",
        "remediation_id": "restart_db_connection_pool",
        "resolution": "Restart the database connection pool to clear blocked transactions.",
    },
    # Authentication
    {
        "symptom": "Users cannot log in, login page keeps spinning and eventually times out",
        "root_cause": "Auth workers are overloaded with heavy bcrypt hashing requests due to a login burst",
        "remediation_id": "scale_workers",
        "resolution": "Scale up the worker instances to handle the burst of authentication requests.",
    },
    {
        "symptom": "Single Sign-On (SSO) page is very slow and intermittently shows 429 Too Many Requests",
        "root_cause": "SSO gateway worker pool is saturated under high morning login traffic",
        "remediation_id": "scale_workers",
        "resolution": "Scale the auth worker service to distribute the SSO authentication load.",
    },
    {
        "symptom": "Active Directory sync is failing and users cannot log in with new passwords",
        "root_cause": "Identity provider token sync process is running out of worker threads",
        "remediation_id": "scale_workers",
        "resolution": "Scale the identity sync workers to process the password update queue.",
    },
    {
        "symptom": "Password reset links are taking over 10 minutes to arrive in user inboxes",
        "root_cause": "Mail delivery worker queue is congested with a backlog of notification tasks",
        "remediation_id": "scale_workers",
        "resolution": "Scale the notification worker pool to speed up password reset email delivery.",
    },
    {
        "symptom": "Multi-factor authentication (MFA) codes are not being verified, page times out after submitting",
        "root_cause": "MFA verification workers are saturated with requests, causing queue timeouts",
        "remediation_id": "scale_workers",
        "resolution": "Scale the MFA verification workers to handle the validation load.",
    },
    # Memory / CPU problems
    {
        "symptom": "Customer search page is extremely slow and server memory usage is at 99%",
        "root_cause": "Memory leak in customer search index worker process — worker threads not being garbage collected",
        "remediation_id": "restart_web_service",
        "resolution": "Restart the web service to terminate bloated worker processes and reclaim memory.",
    },
    {
        "symptom": "API response times have tripled and CPU utilization is pinned at 100%",
        "root_cause": "Runaway background export job consuming all available CPU cycles on the primary web node",
        "remediation_id": "restart_web_service",
        "resolution": "Restart the web service to kill the runaway background task and restore CPU headroom.",
    },
    {
        "symptom": "Server running the backend API keeps crashing with Out Of Memory (OOM) errors",
        "root_cause": "Web service workers accumulated too much heap memory due to massive PDF reports generation",
        "remediation_id": "restart_web_service",
        "resolution": "Restart the web service to clear out memory-heavy PDF generation worker processes.",
    },
    {
        "symptom": "Web dashboard keeps throwing 500 Internal Server Error: 'failed to allocate memory'",
        "root_cause": "Memory fragmentation in the web service process preventing new thread allocations",
        "remediation_id": "restart_web_service",
        "resolution": "Restart the web service to clean up fragmented memory and reallocate resources.",
    },
    {
        "symptom": "Backend API is slow to respond, logs show 'critical: worker process restarted due to memory limit'",
        "root_cause": "Web worker process exceeded its memory ceiling and is constantly thrashing swap space",
        "remediation_id": "restart_web_service",
        "resolution": "Restart the web service to restore workers to their baseline memory consumption.",
    },
    # Additional Network issues (50 Incident Expansion)
    {
        "symptom": "I am unable to access local intranet servers, but google.com and other external sites load fine",
        "root_cause": "Stale corporate DNS cache causing internal domain names to resolve to incorrect IP addresses",
        "remediation_id": "flush_dns",
        "resolution": "Flush the local DNS resolver cache to clear incorrect internal domain mappings.",
    },
    {
        "symptom": "WiFi icon has a yellow exclamation mark and says 'No Internet, Secured' on my workstation",
        "root_cause": "IP address conflict or stale DHCP lease on the wireless network adapter",
        "remediation_id": "reset_network_adapter",
        "resolution": "Reset the network adapter to release and renew the DHCP lease and clear conflicts.",
    },
    {
        "symptom": "VPN connection client is stuck on 'Connecting...' and eventually fails with a security handshaking timeout",
        "root_cause": "Stale VPN client configuration state or active tunnel socket hung in the OS kernel",
        "remediation_id": "reconnect_vpn",
        "resolution": "Force a VPN reconnection to tear down the hung socket and start a clean handshake.",
    },
    {
        "symptom": "Network diagnostics tool says DNS server is not responding, can't open any sites by name",
        "root_cause": "Local TCP/IP stack configuration corrupted after a system update",
        "remediation_id": "reset_network_stack",
        "resolution": "Reset the TCP/IP stack to restore default network interface configurations.",
    },
    {
        "symptom": "Internet connection is incredibly sluggish, running speed tests shows 0.1 Mbps throughput",
        "root_cause": "Network adapter driver buffer bloating under sustained TCP download streams",
        "remediation_id": "reset_network_adapter",
        "resolution": "Reset the network adapter to clear the hardware buffers and restore throughput.",
    },
    {
        "symptom": "Cannot connect to any internet pages after switching my laptop from Ethernet to WiFi dock",
        "root_cause": "Operating system routing table stuck routing packets through the disconnected Ethernet interface",
        "remediation_id": "diagnose_internet",
        "resolution": "Run the internet diagnostics tool to update the routing table and active interface.",
    },
    {
        "symptom": "Corporate chat app works, but all browser traffic is blocked with connection refused errors",
        "root_cause": "Proxy settings configuration corrupted in the local network stack",
        "remediation_id": "reset_network_stack",
        "resolution": "Reset the network stack to purge corrupted proxy routing rules.",
    },
    {
        "symptom": "VPN tunnel disconnects immediately every time my laptop changes access points in the office",
        "root_cause": "VPN routing table not updating with the new local gateway IP",
        "remediation_id": "reconnect_vpn",
        "resolution": "Reconnect the VPN tunnel to bind the routing table to the new local gateway.",
    },
    {
        "symptom": "Cannot resolve custom dev domains like 'service.local' but public web works fine",
        "root_cause": "DNS search suffix cache in the operating system is stale",
        "remediation_id": "flush_dns",
        "resolution": "Flush the DNS cache to rebuild active domain search suffixes.",
    },
    # Additional POS / cashier specific
    {
        "symptom": "Cash register screen is completely unresponsive to barcode scans and touch clicks",
        "root_cause": "POS application process locked up due to an unhandled USB peripheral interrupt",
        "remediation_id": "restart_app_service",
        "resolution": "Restart the POS application service to clear the peripheral lockup.",
    },
    {
        "symptom": "The payment terminal is displaying 'Error: Device Not Initialized' during credit card swipes",
        "root_cause": "POS local device manager service lost communication with the integrated PIN pad",
        "remediation_id": "restart_app_service",
        "resolution": "Restart the POS application service to reinitialize PIN pad communications.",
    },
    {
        "symptom": "Receipts are printing with garbage characters and misplaced symbols",
        "root_cause": "Receipt printer driver buffer corrupted in the cashier terminal service layer",
        "remediation_id": "restart_app_service",
        "resolution": "Restart the POS application service to flush the printer driver buffer.",
    },
    {
        "symptom": "Loyalty member points are showing incorrect balances at checkout",
        "root_cause": "POS cache serving stale customer loyalty data from the previous session",
        "remediation_id": "clear_cache",
        "resolution": "Clear the application cache to retrieve the latest loyalty account details from the server.",
    },
    {
        "symptom": "POS app keeps throwing 'Out of Memory' popups and closing during busy hours",
        "root_cause": "Memory leak in the POS local image cache when loading product thumbnails",
        "remediation_id": "clear_cache",
        "resolution": "Clear the POS application cache to free up leaked memory.",
    },
    {
        "symptom": "Cash drawer does not pop open automatically when completing a cash transaction",
        "root_cause": "Drawer relay command queue hung in the cashier terminal app process",
        "remediation_id": "restart_app_service",
        "resolution": "Restart the POS application service to clear the drawer command queue.",
    },
    {
        "symptom": "Cashier login takes over a minute, terminal hangs on the credential screen",
        "root_cause": "POS local credential cache database has bloated search indices",
        "remediation_id": "clear_cache",
        "resolution": "Clear the local POS application cache to rebuild credential search indices.",
    },
    {
        "symptom": "Handheld scanner works for scanning products, but fails to scan discount coupons",
        "root_cause": "POS local parser service stalled on coupon regex matching",
        "remediation_id": "restart_app_service",
        "resolution": "Restart the POS application service to reset the coupon parser thread.",
    },
    {
        "symptom": "Item price shows $0.00 at checkout, even though the price tag is $10.99",
        "root_cause": "Local pricing database cache failed to sync with the central server",
        "remediation_id": "clear_cache",
        "resolution": "Clear the POS cache to force a fresh pricing catalog synchronization.",
    },
    # Additional Web apps
    {
        "symptom": "Customer dashboard is blank and console shows JavaScript chunk load errors",
        "root_cause": "Old version of web app scripts cached in the browser/app delivery cache after an update",
        "remediation_id": "clear_cache",
        "resolution": "Clear the application cache to force loading of the latest JavaScript assets.",
    },
    {
        "symptom": "Web portal is showing HTTP 500 errors when users try to load their active subscriptions",
        "root_cause": "Subscription microservice web worker pool exhausted due to thread blocking",
        "remediation_id": "restart_web_service",
        "resolution": "Restart the web service to clear blocked threads and restore worker availability.",
    },
    {
        "symptom": "Uploading PDF files to the invoice portal fails with a 502 Bad Gateway error",
        "root_cause": "Web service worker crashed due to memory allocation limit when parsing large PDFs",
        "remediation_id": "restart_web_service",
        "resolution": "Restart the web service to clean up crashed workers and free up memory.",
    },
    {
        "symptom": "Interactive charts on the analytics page are showing outdated data from last week",
        "root_cause": "Web application serving stale API responses from the local Redis data cache",
        "remediation_id": "clear_cache",
        "resolution": "Clear the application cache to force a fresh pull of analytical data.",
    },
    {
        "symptom": "The corporate intranet homepage is loading extremely slowly for all employees",
        "root_cause": "Web service worker threads are saturated with slow synchronous LDAP queries",
        "remediation_id": "restart_web_service",
        "resolution": "Restart the web service to terminate hung LDAP threads and restore response times.",
    },
    {
        "symptom": "User settings updates are not saving, page displays 'Error: Save operation timed out'",
        "root_cause": "Backend web server queue is backlogged with slow write operations",
        "remediation_id": "restart_web_service",
        "resolution": "Restart the web service to clear the backend request queue.",
    },
    {
        "symptom": "Banner images on the e-commerce store are broken, displaying placeholders",
        "root_cause": "Static asset cache directory contains stale file path pointers",
        "remediation_id": "clear_cache",
        "resolution": "Clear the application cache to rebuild the static asset mapping table.",
    },
    {
        "symptom": "Feedback form submission results in a 'csrf token validation failed' error",
        "root_cause": "Session cache has desynchronized token states after a backend node reboot",
        "remediation_id": "clear_cache",
        "resolution": "Clear the application session cache to generate fresh CSRF tokens.",
    },
    # Additional Databases
    {
        "symptom": "Database queries from the reporting app are failing with 'Connection pool timeout' errors",
        "root_cause": "Database connection pool is completely starved by unclosed connections in the reporting tool",
        "remediation_id": "restart_db_connection_pool",
        "resolution": "Restart the database connection pool to reclaim leaked database connections.",
    },
    {
        "symptom": "E-commerce checkout is extremely slow, waiting indefinitely on the checkout step",
        "root_cause": "Database connection pool limit reached, blocking new transaction threads",
        "remediation_id": "restart_db_connection_pool",
        "resolution": "Restart the database connection pool to terminate dead locks and free connection slots.",
    },
    {
        "symptom": "Admin dashboard reports: 'Failed to obtain database connection from pool after 30000ms'",
        "root_cause": "Database pool manager hung due to an internal driver deadlock",
        "remediation_id": "restart_db_connection_pool",
        "resolution": "Restart the database connection pool to clear the driver deadlock state.",
    },
    {
        "symptom": "Application logs show repeated errors: 'psycopg2.OperationalError: pool exhausted'",
        "root_cause": "High concurrent traffic spike caused database connection requests to exceed pool limit",
        "remediation_id": "restart_db_connection_pool",
        "resolution": "Restart the database connection pool to flush queued connection requests.",
    },
    {
        "symptom": "Inventory sync job fails with database connection socket closed errors",
        "root_cause": "Idle connections in the database pool terminated by upstream firewall, leaving stale sockets",
        "remediation_id": "restart_db_connection_pool",
        "resolution": "Restart the database connection pool to purge stale socket connections.",
    },
    {
        "symptom": "Billing database queries are failing intermittently with 'too many clients already' errors",
        "root_cause": "Stale connections from zombie processes are consuming the Postgres primary client slots",
        "remediation_id": "restart_db_connection_pool",
        "resolution": "Restart the database connection pool to release client slots held by zombie connections.",
    },
    {
        "symptom": "App search feature is throwing database connection errors during search queries",
        "root_cause": "Database read replica connection pool hung during a failover event",
        "remediation_id": "restart_db_connection_pool",
        "resolution": "Restart the database connection pool to reconnect to the active replica.",
    },
    {
        "symptom": "Customer history queries fail with connection pool closed errors",
        "root_cause": "Database connection pool was improperly disposed during a network blip",
        "remediation_id": "restart_db_connection_pool",
        "resolution": "Restart the database connection pool to reinitialize the connection manager.",
    },
    # Additional Authentication
    {
        "symptom": "Users logging in are getting redirected back to the login screen without error messages",
        "root_cause": "Authentication worker processes are overloaded and failing to sign JWT tokens in time",
        "remediation_id": "scale_workers",
        "resolution": "Scale up the authentication service workers to distribute token signing load.",
    },
    {
        "symptom": "Active Directory login times out for remote employees using the web portal",
        "root_cause": "LDAP authentication sync workers are saturated with requests due to a company-wide password reset",
        "remediation_id": "scale_workers",
        "resolution": "Scale the authentication workers to handle the burst of LDAP synchronization requests.",
    },
    {
        "symptom": "SSO authentication is failing with HTTP 504 gateway timeout errors on the identity provider",
        "root_cause": "Identity provider worker pool is fully occupied processing heavy SAML signature verifications",
        "remediation_id": "scale_workers",
        "resolution": "Scale the identity provider workers to handle heavy cryptographic verifications.",
    },
    {
        "symptom": "New user signup validation emails are taking hours to arrive in user mailboxes",
        "root_cause": "Email verification worker pool is insufficient for the high volume of new signups",
        "remediation_id": "scale_workers",
        "resolution": "Scale up the email verification workers to speed up signup validation emails.",
    },
    {
        "symptom": "OAuth authorization flow is extremely slow and intermittently returns 503 Service Unavailable",
        "root_cause": "OAuth token validation service is running out of worker processes",
        "remediation_id": "scale_workers",
        "resolution": "Scale the OAuth validation workers to handle the token verification load.",
    },
    {
        "symptom": "Two-factor authentication (2FA) SMS codes are taking over 5 minutes to arrive on user devices",
        "root_cause": "MFA notification queue is backed up due to a shortage of SMS dispatch workers",
        "remediation_id": "scale_workers",
        "resolution": "Scale the SMS dispatch workers to process the MFA notification queue.",
    },
    {
        "symptom": "Password change portal keeps timing out when users click 'Save New Password'",
        "root_cause": "Hashing service workers are saturated with password encryption tasks",
        "remediation_id": "scale_workers",
        "resolution": "Scale up the password hashing workers to process password changes.",
    },
    {
        "symptom": "Session renewal API is very slow, causing the web app to lock up intermittently",
        "root_cause": "Session manager worker instances are running at maximum capacity",
        "remediation_id": "scale_workers",
        "resolution": "Scale the session manager workers to process session renewals.",
    },
    # Additional Memory / CPU Problems
    {
        "symptom": "Web application is sluggish and server logs show 'FATAL: Out of memory'",
        "root_cause": "Memory leak in the web application's session serialization middleware",
        "remediation_id": "restart_web_service",
        "resolution": "Restart the web service to release leaked session serialization memory.",
    },
    {
        "symptom": "API Gateway response latency has jumped from 50ms to 2000ms, CPU usage is 100%",
        "root_cause": "Runaway regex matching process consuming all available CPU on the gateway nodes",
        "remediation_id": "restart_web_service",
        "resolution": "Restart the web service on the gateway nodes to kill the runaway regex matching threads.",
    },
    {
        "symptom": "File export server is unresponsive and memory usage is hovering at 99%",
        "root_cause": "Memory bloat in Excel generation worker processes handling massive datasets",
        "remediation_id": "restart_web_service",
        "resolution": "Restart the web service to terminate bloated Excel generator workers and reclaim memory.",
    },
    {
        "symptom": "Dashboard is extremely slow and logs show 'warning: worker process memory limit exceeded'",
        "root_cause": "Web workers are thrashing swap memory due to a memory leak in report generation",
        "remediation_id": "restart_web_service",
        "resolution": "Restart the web service to clean up bloated workers and restore baseline memory.",
    },
    {
        "symptom": "Web API server is dropping incoming connections and running at 100% CPU",
        "root_cause": "Infinite loop in a background parsing thread consuming all available CPU cores",
        "remediation_id": "restart_web_service",
        "resolution": "Restart the web service to terminate the infinite loop thread and free CPU resources.",
    },
    {
        "symptom": "The application is throwing internal server errors: 'Thread allocation failed'",
        "root_cause": "Web server process ran out of system thread descriptors due to thread leak",
        "remediation_id": "restart_web_service",
        "resolution": "Restart the web service to clear leaked thread descriptors and allow new threads.",
    },
    {
        "symptom": "Web frontend dashboard is completely frozen, browser requests to it time out",
        "root_cause": "Web server process is deadlocked on an internal garbage collection lock",
        "remediation_id": "restart_web_service",
        "resolution": "Restart the web service to clear the deadlocked garbage collection state.",
    },
    {
        "symptom": "Server running the mobile API is slow and logs show high disk thrashing due to swap usage",
        "root_cause": "Memory leaks in API payload deserialization causing workers to exceed physical RAM limits",
        "remediation_id": "restart_web_service",
        "resolution": "Restart the web service to clear leaked RAM in payload deserialization workers.",
    },
]


def _get_collection() -> chromadb.Collection:
    client = chromadb.PersistentClient(path=settings.chroma_dir)
    # Use sentence-transformers (installed locally) instead of the default
    # ONNXMiniLM_L6_V2 which requires downloading a model file from the internet.
    ef = SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=ef,
        metadata={"hnsw:space": "cosine"},
    )


async def ingest_all() -> None:
    """Embed and store all seed incidents into Chroma."""
    collection = _get_collection()

    ids = []
    documents = []
    metadatas: list[dict[str, Any]] = []

    for i, inc in enumerate(SEED_INCIDENTS):
        doc_id = f"seed_{i:04d}"
        # Document text: symptom + root_cause (what the user describes + diagnosis)
        doc_text = f"{inc['symptom']} | {inc['root_cause']}"
        ids.append(doc_id)
        documents.append(doc_text)
        metadatas.append(
            {
                "symptom": inc["symptom"],
                "root_cause": inc["root_cause"],
                "remediation_id": inc["remediation_id"],
                "resolution": inc["resolution"],
            }
        )

    # Upsert (idempotent)
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        lambda: collection.upsert(ids=ids, documents=documents, metadatas=metadatas),
    )
    logger.info("[ingest] %d incidents ingested into Chroma collection '%s'", len(ids), COLLECTION_NAME)
    print(f"[ingest] {len(ids)} incidents ingested into Chroma.")


async def ingest_resolution(
    symptom: str,
    root_cause: str,
    remediation_id: str,
    ticket_id: str,
) -> None:
    """Write a newly resolved incident back to Chroma (learning loop)."""
    collection = _get_collection()
    doc_id = f"resolved_{ticket_id}"
    doc_text = f"{symptom} | {root_cause}"
    resolution_text = f"Run the '{remediation_id}' runbook to resolve this issue."

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        lambda: collection.upsert(
            ids=[doc_id],
            documents=[doc_text],
            metadatas=[
                {
                    "symptom": symptom,
                    "root_cause": root_cause,
                    "remediation_id": remediation_id,
                    "resolution": resolution_text,
                    "ticket_id": ticket_id,
                }
            ],
        ),
    )
    logger.info("[ingest] Resolution for ticket %s written to Chroma", ticket_id)


if __name__ == "__main__":
    asyncio.run(ingest_all())
