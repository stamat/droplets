var api_key = 'aa4e907633d320199addca746884ec69';
var user = 'thestamat';
var limit = 5;
var trim_brackets = false;

$(document).ready(function(){
	
	if((limit == null)||(limit == undefined))
		limit = 10;

	appendStructure('#container');
	
	$('#lastbadge li').hover(
		function(){
			$(this).addClass('hover');
		},
		function(){
			$(this).removeClass('hover');
		}
	);
	
	$('#lastbadge .user').hover(
		function(){
			$('#lastbadge .user .name').addClass('hover');
		},
		function(){
			$('#lastbadge .user .name').removeClass('hover');
		}
	);
	
	ajax('GET','http://ws.audioscrobbler.com/2.0/?method=user.getrecenttracks&user='+user+'&limit='+limit+'&api_key='+ api_key+'&format=json', parseRecentTracks);
	ajax('GET','http://ws.audioscrobbler.com/2.0/?method=user.getinfo&user='+user+'&api_key='+ api_key+'&format=json', parseInfo);

});

function appendStructure(where) {
	$(where).append('<div id="lastbadge"><a class="profile-url" href=""><div class="user"><div class="avatar"><img src=""/></div><div class="name"><p><span class="data"></span></p></div><div class="total"><p>Plays: <span class="data"></span></p></div><div class="logo"><img src="http://dl.dropbox.com/u/2808807/projects/lastbadge/logo.png"/></div></div></a><ul class="songs clearfix"></ul></div>');
	
	var html = '';
	
	for(var i = 0; i < limit; i++ ) {
		var second = '';
		if(i%2 != 0)
			second = 'sec';
		html += trackHtml(i, second);
	}
	
	$('#lastbadge .songs').append(html);
}

function trackHtml(id, second) {
	return 	'<li id="lsfm-song'+id+'" class="song '+second+'"><a href="" title=""> \n'+
				'<div class="wrapper clearfix"> \n' +
					'<div class="cover meta"> <img src="http://dl.dropbox.com/u/2808807/projects/lastbadge/loading.gif"/></div>'+
					'<div class="name meta"> <p class="data"></p></div>'+
					'<div class="artist meta"> <p class="data"></p></div>'+
					'<div class="date meta"> <p class="data"></p></div>'+
				'</div>' +
			'</a></li>'
}

function parseRecentTracks(json) {
	for(var i = 0; i < json.recenttracks.track.length; i++ ) {
		var current = json.recenttracks.track[i];
		var name = current.name
		if(trim_brackets) {
			var bracket_id = name.indexOf('(');
			if(bracket_id >0)
				name = name.substring(0, bracket_id);
		}
		
		if(current.date == undefined)
			date = 'Playing now';
		else
			date = parseTime(current.date.uts);
			
		var image = current.image[0]['#text'];
		if(image == undefined)
			image = 'http://dl.dropbox.com/u/2808807/projects/lastbadge/no_image.png';

		addTrackData(i, name, current.artist['#text'], image, current.url, date);
	}
}

function parseInfo(json) {
	$('#lastbadge .profile-url').attr('href', json.user.url).attr('title', json.user.realname);
	$('#lastbadge .user .avatar img').attr('src', json.user.image[0]['#text']);
	$('#lastbadge .user .name .data').html(json.user.name);
	$('#lastbadge .user .total .data').html(json.user.playcount);
	
}

function addTrackData(id, song, artist, image, url, date) {
	var song_id = '#lsfm-song'+id;
	
	$(song_id +' a').attr('href', url).attr('title', song+' - '+artist);
	$(song_id +' .cover img').attr('src', image);
	$(song_id +' .name .data').html(song);
	$(song_id +' .artist .data').html(artist);
	$(song_id +' .date .data').html(date);

}

function parseTime(uts) {
	var now = Math.round(new Date().getTime()/1000);
	var time = parseInt(uts);
	var date = new Date(time*1000);
	
	var months = new Array(12);
	months[0]  = "Jan";
	months[1]  = "Feb";
	months[2]  = "Mar";
	months[3]  = "Apr";
	months[4]  = "May";
	months[5]  = "Jun";
	months[6]  = "Jul";
	months[7]  = "Aug";
	months[8]  = "Sep";
	months[9]  = "Oct";
	months[10] = "Nov";
	months[11] = "Dec";
	
	var diff = (now - time)/60;
	if(diff < 60)
		return Math.round(diff)+" minutes ago";
	else if (diff/60<24)
		return Math.round(diff/60)+" hours ago";
	else if (diff/60<48)
		return "Yesterday "+date.getHours()+":"+date.getMinutes();
	else if (diff/60>48)
		return date.getDate()+'.'+months[date.getMonth()]+' '+date.getHours()+":"+date.getMinutes();
}

function ajax(method, url, callback, data) {
	var request = new XMLHttpRequest();
	request.open(method, url, true); 
	request.onload = function(e) {
		if (request.status == 200)
			callback(JSON.parse(request.responseText));
	}
	
	if(data != undefined)
		request.send(data);
	else
		request.send();
}
