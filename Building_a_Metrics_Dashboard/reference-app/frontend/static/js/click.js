$(document).ready(function () {

    // Button 1 sends request to backend API
    $("#firstbutton").click(function () {
        $.ajax({
            url: "http://backend.local/api",
            success: function (result) {
                $("#firstbutton").toggleClass("btn-primary:focus");
            }
        });
    });

    // Button 2 sends request to trial service
    $("#secondbutton").click(function () {
        $.ajax({
            url: "http://trial.local/",
            success: function (result) {
                $("#secondbutton").toggleClass("btn-primary:focus");
            }
        });
    });    
});