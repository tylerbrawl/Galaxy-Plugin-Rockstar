window.onerror = function (msg, url, lineNum) {
    alert('Error: ' + msg + ' / Line Number: ' + lineNum);
    return false;
}

var fpImport = document.createElement('script');
fpImport.src = 'https://tylerbrawl.github.io/Galaxy-Plugin-Rockstar/fingerprint2.js';
document.head.appendChild(fpImport);

var hashImport = document.createElement('script');
hashImport.src = 'https://tylerbrawl.github.io/Galaxy-Plugin-Rockstar/HashGen.js';
document.head.appendChild(hashImport);

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
        alert('Fingerprint: ' + fpString);
        document.cookie = ('fingerprint=' + fpString); //+ '; expires=' + expiry + '; path=/';
	});
}, 500);

setTimeout(function () {
    document.location.href = "https://www.rockstargames.com/auth/scauth-login";
}, 1000);
