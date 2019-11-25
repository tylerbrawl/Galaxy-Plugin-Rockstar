window.onerror = function (msg, url, lineNum) {
    alert('Error: ' + msg + ' / Line Number: ' + lineNum);
    return false;
}

var options = {
	swfContainerId: 'fingerprintjs2',
	swfPath: 'flash/compiled/FontList.swf',
	detectScreenOrientation: false,
	sortPluginsFor: [/palemoon/i],
	excludeColorDepth: true,
	excludeScreenResolution: true,
	excludeAddBehavior: true,
	excludeHasLiedLanguages: true,
	excludeUserTamperedWithScreenRes: true,
	excludeHasLiedResolution: true,
	excludeHasLiedBrowser: true,
	excludeFlashFonts: true,
	excludeAvailableScreenResolution: true,
	excludeIEPlugins: true
};

setTimeout(function() {
    var fp = new Fingerprint2(options);
	fp.get(function(result, components) {
		var fpString = '{"fp":{';
		for(var i = 0; i < components.length; i++) {
			var object = components[i];
			var key = object.key;
			if(typeof object.value == "string" || typeof object.value == "object") {
				var workingValue;
				if(typeof object.value.join !== "undefined")
					workingValue = object.value.join(";");
				else
					workingValue = object.value;
				var value = (workingValue.length > 32 && key !== "device_name" ?
					x64hash128Gen(workingValue, 31) :
					workingValue);
				fpString += '"' + key + '":"' + value + '"';
			}
			else {
				var value = object.value;
				fpString += '"' + key + '":' + value;
			}
			if(i != (components.length - 1))
				fpString += ',';
		}
        fpString += '}}';
	
	//Galaxy 2.0's cookie extraction cuts off the name of the cookie after the first semicolon (;), so all occurrences of semicolons
	//will be temporarily replaced with dollar signs ($), as I have yet to see this character used in a fingerprint.
        document.cookie = ('fingerprint=' + fpString.replace(/;/g, "$")); //+ '; expires=' + expiry + '; path=/';
	});
}, 500);
