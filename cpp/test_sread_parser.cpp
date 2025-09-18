/**
 * @file test_sread_parser.cpp
 * @author Denis Kudia (dkudja@gmail.com)
 * @brief
 * @version 0.1
 * @date 2025-08-07
 *
 * @copyright Copyright (c) 2025
 *
 */

#include <stdlib.h>
#include <iostream>
#include <string>
#include "rapidjson/document.h"
#include "smallthings.h"
#include "defines.h"


int main (int argc, char* argv[])
{
    if(argc < 2){
        std::cout << "File name is absent" << std::endl;
        exit(EXIT_FAILURE);
    }

    FILE *fp; // Declare a file pointer
    char buffer[MAX_LINE_LENGTH]; // Declare a character array (buffer) to store the line

    // Open the file in read mode ("r")
    fp = fopen(argv[1], "r");

    // Check if the file was opened successfully
    if (fp == NULL) {
        perror("Error opening file"); // Print an error message
        exit(EXIT_FAILURE); // Exit the program with an error status
    }


    std::cout << "Started loading.... " << piutils::get_time_string(false) << std::endl;

    if(fgets(buffer, MAX_LINE_LENGTH, fp) != NULL) {
        rapidjson::Document d;

        std::cout << "Started parsing.... " << piutils::get_time_string(false) << std::endl;
        d.Parse(buffer);
        std::cout << "Finished parsing.... " << piutils::get_time_string(false) << std::endl;

        if(d.HasParseError()){
            auto err = d.GetParseError();
            std::cout << "Parse error: " << std::to_string(err) << " Offset: " << d.GetErrorOffset() << std::endl;
        }
        else{
            std::cout << "Parse successfull. Memebers count: " << d.MemberCount() << std::endl;

            for(auto v = d.MemberBegin(); v != d.MemberEnd(); ++v){
                  std::cout << "Name: " << v->name.GetString() << std::endl;
            }

            auto v_nothing = d.FindMember("nothing");
            auto v_claims = d.FindMember("claims");

            if(v_nothing == d.MemberEnd()){
                std::cout << "No such member: " << "nothing" << std::endl;
            }

            if(v_claims != d.MemberEnd()){
                std::cout << "Name: " << v_claims->name.GetString() << " Type: " << v_claims->value.GetType() << " Count: "
                    << v_claims->value.MemberCount() << std::endl;
            }
            else
                std::cout << "No such member: " << "claims" << std::endl;

        }

    }


    fclose(fp);

    exit(EXIT_SUCCESS);
}