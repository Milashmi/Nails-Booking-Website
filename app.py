from flask import Flask, render_template, request

app = Flask(__name__)

services = [
    {
        "name": "Gel Nail Extension",
        "price": "Rs.1000",
        "image": "nails1.jpg"
    },
    {
        "name": "Acrylic Nails",
        "price": "Rs.1500",
        "image": "nails2.jpg"
    },
    {
        "name": "French Tips",
        "price": "Rs.1200",
        "image": "nails3.jpg"
    }
]

@app.route("/")
def home():
    return render_template("home.html", services=services)

@app.route("/booking", methods=["GET", "POST"])
def booking():

    if request.method == "POST":

        username = request.form["username"]
        service = request.form["service"]
        date = request.form["date"]
        time = request.form["time"]

        print(username, service, date, time)

        return render_template(
            "success.html",
            username=username
        )

    return render_template("booking.html")

if __name__ == "__main__":
    app.run(debug=True)