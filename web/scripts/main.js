const refreshCheckbox = document.querySelector('#refreshOnOff');
const refreshDelay = document.querySelector('#refreshDelay');
currentlyRefreshing = false;
refreshCheckbox.addEventListener('click', updateRefreshDelay);

function updateQueue() {
  $.get("/queueUpdate", function(data, status){
    $('#DATA').html(data);
    console.log(data);
  });
}
function editQueue(action) {
  var url = "/edit";
  var formData = {};
  formData["action"] = action;
  formData["filename"] = $('input[name=filename]:checked', '#queue').val();
  $.post(url, formData);
}
function uploadFile(form) {
  $.ajax({
    // Your server script to process the upload
    url: '/upload',
    type: 'POST',

    // Form data
    data: new FormData($('#fileUpload')[0]),

    // Tell jQuery not to process data or worry about content-type
    // You *must* include these options!
    cache: false,
    contentType: false,
    processData: false,

    // Custom XMLHttpRequest
    xhr: function () {
      var myXhr = $.ajaxSettings.xhr();
      if (myXhr.upload) {
        // For handling the progress of the upload
        myXhr.upload.addEventListener('progress', function (e) {
          if (e.lengthComputable) {
            $('progress').attr({
              value: e.loaded,
              max: e.total,
            });
          }
        }, false);
      }
      return myXhr;
    }
  });
}
function updateRefreshDelay() {
  if (refreshCheckbox.checked && !currentlyRefreshing) {
    currentlyRefreshing = true;
    refreshLoop();
  }
}
function refreshLoop() {
   setTimeout(() => {
      updateQueue();

      if (refreshCheckbox.checked) {
        refreshLoop();
      }
      else {
        currentlyRefreshing = false;
      }
  }, refreshDelay.value * 1000);
}
function checkForSoftwareUpdate() {
  $.get("/softwareUpdate", function(data, status){
    $('#SOFTWAREUPDATE').html(data);
    console.log(data);
  });
}