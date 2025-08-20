// Frontend Integration Example for Device Replacement API
// This is a sample JavaScript function showing how to use the device replacement endpoint

/**
 * Check if a device needs replacement and show/hide replacement button
 * @param {string} deviceSerial - The device serial number
 * @param {HTMLElement} buttonElement - The replacement button element
 */
async function checkDeviceReplacement(deviceSerial, buttonElement) {
    try {
        // Call the device replacement API
        const response = await fetch(`http://localhost:8080/device-replacement/${deviceSerial}`);
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        const data = await response.json();
        
        // Main boolean check - this is what frontend needs
        const shouldShowButton = data.replace_device;
        
        if (shouldShowButton) {
            // Show the replacement button
            buttonElement.style.display = 'block';
            buttonElement.className = 'replacement-button warning';
            
            // Update button text with reasons
            if (data.reasons && data.reasons.length > 0) {
                buttonElement.title = `Device replacement recommended: ${data.reasons.join(', ')}`;
            }
            
            console.log(`🔴 Device ${deviceSerial} needs replacement:`, data.reasons);
        } else {
            // Hide the replacement button
            buttonElement.style.display = 'none';
            console.log(`✅ Device ${deviceSerial} is performing normally`);
        }
        
        // Optional: Display detailed metrics
        if (data.metrics) {
            console.log(`📊 Device metrics - CPU: ${data.metrics.avg_cpu}%, Memory: ${data.metrics.avg_memory}%`);
        }
        
        return shouldShowButton;
        
    } catch (error) {
        console.error('Error checking device replacement:', error);
        
        // On error, hide the button (fail safe)
        buttonElement.style.display = 'none';
        return false;
    }
}

/**
 * Monitor multiple devices and update UI accordingly
 * @param {Array} deviceList - List of device serial numbers
 */
async function monitorDevices(deviceList) {
    for (const deviceSerial of deviceList) {
        const buttonElement = document.getElementById(`replace-btn-${deviceSerial}`);
        
        if (buttonElement) {
            await checkDeviceReplacement(deviceSerial, buttonElement);
        }
    }
}

/**
 * Set up periodic checking (e.g., every 5 minutes)
 * @param {Array} deviceList - List of device serial numbers
 */
function setupPeriodicCheck(deviceList) {
    // Initial check
    monitorDevices(deviceList);
    
    // Check every 5 minutes
    setInterval(() => {
        monitorDevices(deviceList);
    }, 5 * 60 * 1000);
}

// Example usage:
// const devices = ['GWHV4X1Y4L', 'DEVICE123', 'LAPTOP456'];
// setupPeriodicCheck(devices);

// Example HTML structure needed:
/*
<div class="device-card" data-device="GWHV4X1Y4L">
    <h3>Device: GWHV4X1Y4L</h3>
    <button 
        id="replace-btn-GWHV4X1Y4L" 
        class="replacement-button" 
        style="display: none;"
        onclick="initiateReplacement('GWHV4X1Y4L')"
    >
        Replace Device
    </button>
</div>
*/

// CSS for the button:
/*
.replacement-button {
    background-color: #ff6b6b;
    color: white;
    border: none;
    padding: 10px 20px;
    border-radius: 5px;
    cursor: pointer;
    font-weight: bold;
}

.replacement-button:hover {
    background-color: #ff5252;
}

.replacement-button.warning {
    animation: pulse 2s infinite;
}

@keyframes pulse {
    0% { transform: scale(1); }
    50% { transform: scale(1.05); }
    100% { transform: scale(1); }
}
*/
